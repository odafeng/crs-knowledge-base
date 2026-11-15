"""Lightweight triage for commentary: editorials, letters, comments, news.

Commentary is not added to the KB as a paper and never goes through the full
classification agent. If it discusses a trial already in the KB, it becomes a
proposed "related commentary" entry on that trial's card. Proposals go to a
review issue first (ADR-0003: nothing AI-written is published unreviewed);
commentary that maps to no KB trial is only recorded in tracked DOIs.
"""

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from config import CLASSIFY_MODEL, FALLBACK_BETA, TRIAGE_EFFORT
from usage import USAGE

if TYPE_CHECKING:
    from anthropic import Anthropic

# Most specific first: a letter that comments on a trial is reported as "Letter".
COMMENTARY_TYPES: tuple[str, ...] = ("Editorial", "Letter", "News", "Newspaper Article", "Comment")

# PubMed also tags some original research "Comment"; any of these keeps it in full classification.
PRIMARY_RESEARCH_TYPES = frozenset(
    {
        "Randomized Controlled Trial",
        "Clinical Trial",
        "Clinical Trial, Phase I",
        "Clinical Trial, Phase II",
        "Clinical Trial, Phase III",
        "Clinical Trial, Phase IV",
        "Controlled Clinical Trial",
        "Pragmatic Clinical Trial",
        "Multicenter Study",
        "Observational Study",
        "Comparative Study",
        "Validation Study",
        "Meta-Analysis",
        "Systematic Review",
        "Practice Guideline",
        "Guideline",
    }
)

MatchMethod = Literal["comment_on", "ai"]


@dataclass
class KBPaper:
    id: str
    topic: str
    year: int
    journal: str
    regimen: str
    doi: str | None


@dataclass
class CommentaryProposal:
    target_id: str | None
    doi: str
    pmid: str
    title: str
    journal: str
    year: int | None
    type: str
    summary: str
    critique: bool
    new_data: bool
    match_method: MatchMethod | None

    def to_entry(self, added_at: str) -> dict:
        """The papers.json ``commentary`` item for this proposal."""
        return {
            "doi": self.doi or None,
            "pmid": self.pmid or None,
            "title": self.title,
            "journal": self.journal,
            "year": self.year,
            "type": self.type,
            "summary": self.summary,
            "critique": self.critique,
            "newData": self.new_data,
            "addedAt": added_at,
        }


def commentary_type(paper: dict) -> str | None:
    """The commentary type of a candidate, or None if it is (or may be) original research."""
    types = set(paper.get("publication_types") or [])
    if types & PRIMARY_RESEARCH_TYPES:
        return None
    return next((t for t in COMMENTARY_TYPES if t in types), None)


def split_commentary(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split candidates into (original research, commentary)."""
    research, commentary = [], []
    for c in candidates:
        (commentary if commentary_type(c) else research).append(c)
    return research, commentary


def kb_papers(data: dict) -> list[KBPaper]:
    """Papers a commentary can attach to (topics with a ``papers`` list)."""
    return [
        KBPaper(p["id"], topic, p["year"], p["journal"], p["regimen"], p.get("doi"))
        for topic, topic_data in data.items()
        for p in topic_data.get("papers", [])
    ]


def match_by_comment_on(
    paper: dict, kb: list[KBPaper], resolve_dois: Callable[[list[str]], dict[str, str]]
) -> str | None:
    """Deterministic match: PubMed's CommentOn PMIDs resolved to DOIs, compared with KB DOIs."""
    pmids = paper.get("comment_on_pmids") or []
    if not pmids:
        return None
    by_doi = {p.doi.lower(): p.id for p in kb if p.doi}
    for doi in resolve_dois(pmids).values():
        if doi and doi.lower() in by_doi:
            return by_doi[doi.lower()]
    return None


def _triage_schema(kb_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "target_id": {"anyOf": [{"type": "string", "enum": kb_ids}, {"type": "null"}]},
            "summary": {"type": "string"},
            "has_substantive_critique": {"type": "boolean"},
            "has_new_data": {"type": "boolean"},
        },
        "required": ["target_id", "summary", "has_substantive_critique", "has_new_data"],
        "additionalProperties": False,
    }


TRIAGE_SYSTEM_PROMPT = """你是大腸直腸癌知識庫的文獻助理。輸入是一篇評論類文章（社論、讀者來信、評論、新聞）與知識庫已收錄的試驗清單。

請判斷：
1. target_id：這篇文章主要在討論清單中的哪一篇試驗。只有在明確討論該試驗（同一試驗名稱或同一研究）時才填；討論的是清單外的研究、或只是泛論某個領域時填 null。
2. summary：一行繁體中文摘要（60 字以內），說明這篇評論的論點。只能根據提供的標題與摘要，不得加入摘要沒有的數字。
3. has_substantive_critique：是否對該試驗提出實質批評，例如方法學問題、對結論的質疑、替代解讀。單純肯定或介紹結果為 false。
4. has_new_data：是否包含原始報告沒有的新數據，例如更新追蹤、次分析數字、作者回覆中補充的結果。"""


def _triage_prompt(paper: dict, kb: list[KBPaper], comment_on_target: str | None) -> str:
    lines = [
        f"## 評論文章（{commentary_type(paper)}）",
        f"標題：{paper.get('title', '')}",
        f"期刊：{paper.get('journal', '')} {paper.get('year', '')}",
        f"摘要：{paper.get('abstract') or '（無摘要）'}",
        "",
        "## 知識庫已收錄試驗（id ｜ 年份 期刊 ｜ 方案）",
        *(f"- {p.id} ｜ {p.year} {p.journal} ｜ {p.regimen}" for p in kb),
    ]
    if comment_on_target:
        lines += ["", f"PubMed 標示這篇文章是在評論 {comment_on_target}，target_id 請填它。"]
    return "\n".join(lines)


def triage_commentary(
    client: "Anthropic",
    paper: dict,
    kb: list[KBPaper],
    resolve_dois: Callable[[list[str]], dict[str, str]],
) -> CommentaryProposal | None:
    """One short structured-output call; None if the model declines."""
    comment_on_target = match_by_comment_on(paper, kb, resolve_dois)
    response = client.beta.messages.create(
        model=CLASSIFY_MODEL,
        max_tokens=8000,
        output_config={
            "effort": TRIAGE_EFFORT,
            "format": {"type": "json_schema", "schema": _triage_schema([p.id for p in kb])},
        },
        system=TRIAGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _triage_prompt(paper, kb, comment_on_target)}],
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    USAGE.record(response, CLASSIFY_MODEL)
    if response.stop_reason == "refusal":
        print(f"    [WARN] Commentary triage declined: {paper.get('title', '')[:60]}", file=sys.stderr)
        return None
    result = json.loads(next(b.text for b in response.content if b.type == "text"))

    # PubMed's CommentOn link is authoritative over the model's pick.
    target = comment_on_target or result["target_id"]
    year = str(paper.get("year", ""))
    return CommentaryProposal(
        target_id=target,
        doi=paper.get("doi", ""),
        pmid=paper.get("pmid", ""),
        title=paper.get("title", ""),
        journal=paper.get("journal", ""),
        year=int(year) if year.isdigit() else None,
        type=commentary_type(paper) or "Comment",
        summary=result["summary"],
        critique=result["has_substantive_critique"],
        new_data=result["has_new_data"],
        match_method=("comment_on" if comment_on_target else "ai") if target else None,
    )


def apply_commentary(data: dict, items: list[tuple[str, dict]]) -> list[str]:
    """Add ``(target_id, entry)`` items to papers.json data. Returns target ids changed.

    An entry whose DOI (or PMID) is already on the target card is skipped.
    """
    papers = {p["id"]: p for t in data.values() for p in t.get("papers", [])}
    changed = []
    for target_id, entry in items:
        paper = papers[target_id]
        existing = paper.setdefault("commentary", [])
        key = entry.get("doi") or entry.get("pmid")
        if any((c.get("doi") or c.get("pmid")) == key for c in existing):
            continue
        existing.append(entry)
        changed.append(target_id)
    return changed
