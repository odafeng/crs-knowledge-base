"""Write classified papers and commentary into the KB, and take them back out (ADR-0013).

Used by the pipeline for gate-passing items (review status "auto"), by the
accepted-label workflow for items a human approved ("accepted"), and by the
unpublish workflow. Every write is validated with validate_data() before any
file is touched; an invalid result raises PublishError and leaves the KB as it was.
"""

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from commentary import apply_commentary
from provenance import check_evidence, evaluate_paper_gate, evidence_table_markdown, published_fields
from validate import validate_data

ROOT = Path(__file__).resolve().parent.parent

# robotic-surgery renders hand-written HTML cards (tme_cards), not a papers list.
AUTO_PUBLISH_TOPICS = {
    "mCRC-BRAF-V600E",
    "mCRC-KRAS-G12C",
    "mCRC-MSI-H",
    "mCRC-HER2",
    "mCRC-RAS-wt",
    "generic-CRS",
}

# Must match validate.REVIEW_STATUSES.
ReviewStatus = Literal["auto", "accepted"]
RELATION_TYPES = {"builds_on", "supersedes", "subgroup_of", "same_regimen", "contradicts"}

_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


class PublishError(Exception):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


#: "json" while data/*.json is the content authority; the cutover to PostgreSQL writes "postgres" (E2 #73).
WRITER_FILE = "data/WRITER"


def json_writer_active(root: Path = ROOT) -> bool:
    flag = root / WRITER_FILE
    return not flag.exists() or flag.read_text(encoding="utf-8").strip() == "json"


@dataclass
class KB:
    """The files a publish touches, rooted at the repository (tests use a temp copy)."""

    root: Path = ROOT

    @property
    def papers_json(self) -> Path:
        return self.root / "data" / "papers.json"

    @property
    def news_json(self) -> Path:
        return self.root / "data" / "news.json"

    def load(self) -> dict:
        return json.loads(self.papers_json.read_text())

    def save(self, data: dict) -> None:
        if not json_writer_active(self.root):
            raise PublishError(["內容已改由資料庫寫入（data/WRITER），JSON 檔不再接受發布或撤下"])
        self.papers_json.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _esc(value):
    """HTML-escape model-written strings before storing them in the KB."""
    return html.escape(value, quote=False) if isinstance(value, str) else value


def _int_or_none(value) -> int | None:
    return int(value) if isinstance(value, int) or (isinstance(value, str) and value.isdigit()) else None


def build_entry(paper: dict, data: dict, review: ReviewStatus, today: str) -> dict:
    """A papers.json entry from a classified paper. Relations to unknown ids are dropped."""
    js = paper.get("ai_suggested_js") or {}
    entry_id = str(js.get("id", ""))
    if not _SAFE_NAME.fullmatch(entry_id):
        raise PublishError([f"不合法的 id：{entry_id!r}"])

    filename = paper.get("ai_suggested_filename") or ""
    if not (_SAFE_NAME.fullmatch(filename) and filename.endswith(".html")):
        filename = f"{entry_id}.html"

    known_ids = {p["id"] for t in data.values() for p in t.get("papers", [])}
    relations = [
        {"targetId": r["targetId"], "type": r["type"]}
        for r in js.get("relations") or []
        if r.get("targetId") in known_ids and r.get("type") in RELATION_TYPES
    ]
    n = js.get("n")
    return {
        "id": entry_id,
        "year": _int_or_none(js.get("year")) or _int_or_none(paper.get("year")),
        "journal": _esc(js.get("journal") or paper.get("journal", "")),
        "studyType": js.get("studyType", ""),
        "n": n if isinstance(n, int) else _esc(n) if n else None,
        "regimen": _esc(js.get("regimen", "")),
        "endpoint": _esc(js.get("endpoint", "")),
        "result": _esc(js.get("result", "")),
        "bottomLine": _esc(published_fields(paper)["bottomLine"]),
        "doi": paper.get("doi") or js.get("doi") or None,
        "file": f"docs/{paper['topic']}/{filename}",
        "relations": relations,
        # "abstract" only when every number passes the provenance gate. Accepted papers were
        # usually held because some numbers came from elsewhere, so they keep the warning.
        "source": "abstract" if evaluate_paper_gate(paper, AUTO_PUBLISH_TOPICS).passed else "secondary",
        "reviewedAt": today,
        "review": {"status": review, "publishedAt": today},
    }


_BANNERS = {
    "auto": (
        "#fffbeb",
        "#b7791f",
        "AI 自動整理，未經人工審核。所有數字已逐字比對 PubMed 摘要，但仍可能有判讀錯誤，請以原文為準。",
    ),
    "accepted": ("#ebf8ff", "#2b6cb0", "AI 整理，已經人工確認後發布。"),
}

_DOC_STYLE = """body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 16px; line-height: 1.7; color: #1a202c; background: #fff; }
h1 { font-size: 1.3rem; color: #1a365d; border-bottom: 2px solid #3182ce; padding-bottom: 8px; }
h2 { font-size: 1.1rem; color: #2c5282; margin-top: 24px; }
.meta { background: #f7fafc; padding: 12px; border-radius: 8px; margin: 12px 0; font-size: 0.88rem; color: #4a5568; }
.meta a { color: #3182ce; }
table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 0.85rem; }
th, td { border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #edf2f7; color: #1a365d; }
.note { background: #fffbeb; border-left: 3px solid #d69e2e; padding: 8px 12px; margin: 12px 0; border-radius: 0 6px 6px 0; }
.banner { padding: 8px 12px; border-radius: 6px; font-size: 0.85rem; margin: 12px 0; }
p { margin: 8px 0; }"""

_CHECK_LABELS = {"verified": "✓ 摘要中找到", "not_found": "✗ 摘要中找不到", "web": "網頁", "inference": "推論"}


def render_doc_page(paper: dict, entry: dict) -> str:
    """Detail page for a published paper. Every model-written string is escaped."""
    e = html.escape
    bg, fg, banner = _BANNERS[entry["review"]["status"]]
    checks = check_evidence(paper.get("ai_evidence") or [], paper.get("abstract", ""))
    evidence_rows = "\n".join(
        f"<tr><td>{e(c.claim)}</td><td>{e(c.quote or c.url or '—')}</td><td>{_CHECK_LABELS.get(c.status, c.status)}</td></tr>"
        for c in checks
    )
    doi = entry.get("doi") or ""
    doi_html = f'<a href="https://doi.org/{e(doi)}">{e(doi)}</a>' if doi else "—"
    title = e(paper.get("title", entry["id"]))
    # entry fields are already escaped by build_entry
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
{_DOC_STYLE}
</style>
</head>
<body>

<h1>{title}</h1>

<div class="banner" style="background:{bg};color:{fg}">{banner}</div>

<div class="meta">
<strong>Journal:</strong> <em>{entry["journal"]}</em> {entry["year"] or ""}<br>
<strong>DOI:</strong> {doi_html}<br>
<strong>PMID:</strong> {e(str(paper.get("pmid") or "—"))}<br>
<strong>Study:</strong> {e(entry["studyType"])}{f"，n={entry['n']}" if entry["n"] else ""}
</div>

<div class="note">
<strong>Bottom Line:</strong> {entry["bottomLine"]}
</div>

<h2>Key Results</h2>
<table>
<tr><th>方案</th><td>{entry["regimen"]}</td></tr>
<tr><th>主要終點</th><td>{entry["endpoint"]}</td></tr>
<tr><th>結果</th><td>{entry["result"]}</td></tr>
</table>

<h2>AI 分析</h2>
<p>{e(paper.get("ai_analysis") or "")}</p>

<h2>數字出處</h2>
<table>
<tr><th>數字</th><th>摘要原文</th><th>核對</th></tr>
{evidence_rows}
</table>

<details><summary>PubMed 摘要</summary>
<p>{e(paper.get("abstract") or "")}</p>
</details>

<p style="font-size:0.75rem;color:#718096;border-top:1px solid #e2e8f0;margin-top:24px;padding-top:8px">本頁僅供醫療專業人員教育與臨床參考，不構成醫療建議；臨床決策請以原始文獻與現行指引為準。</p>

</body>
</html>
"""


def _check(data: dict, kb: KB, pending_files: frozenset[str] = frozenset()) -> None:
    errors = validate_data(data, kb.root, pending_files)
    if errors:
        raise PublishError(errors)


def publish_paper(paper: dict, review: ReviewStatus, today: str, kb: KB | None = None) -> dict:
    """Add the paper and its detail source. The site build generates pages and precache assets."""
    kb = kb or KB()
    topic = paper.get("topic")
    if topic not in AUTO_PUBLISH_TOPICS:
        raise PublishError([f"topic `{topic}` 不支援自動發布"])
    data = kb.load()
    entry = build_entry(paper, data, review, today)
    doc_path = kb.root / entry["file"]
    if doc_path.exists():
        raise PublishError([f"詳細頁已存在：{entry['file']}"])
    data[topic]["papers"].append(entry)
    _check(data, kb, frozenset({entry["file"]}))

    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(render_doc_page(paper, entry))
    kb.save(data)
    return entry


def publish_commentary(
    items: list[tuple[str, dict]], review: ReviewStatus, today: str, kb: KB | None = None
) -> list[str]:
    """Attach commentary entries to KB papers. Returns the target ids changed."""
    kb = kb or KB()
    data = kb.load()
    stamped = [
        (target, {**{k: _esc(v) for k, v in entry.items()}, "review": {"status": review, "publishedAt": today}})
        for target, entry in items
    ]
    changed = apply_commentary(data, stamped)
    _check(data, kb)
    kb.save(data)
    return changed


def _drop_references(data: dict, paper_id: str) -> None:
    """Remove relations and treatment-card refs pointing at ``paper_id``, in every topic."""
    for topic_data in data.values():
        for p in topic_data.get("papers", []):
            p["relations"] = [r for r in p.get("relations", []) if r.get("targetId") != paper_id]
        for card in topic_data.get("standard_of_care", {}).get("cards", []):
            card["refs"] = [ref for ref in card.get("refs", []) if ref != paper_id]


def unpublish(target: str, kb: KB | None = None) -> str:
    """Remove a bot-published paper (by id) or commentary (by DOI or PMID). Returns what was removed.

    Hand-curated entries (no ``review`` field) are refused: those are edited in git directly.
    """
    kb = kb or KB()
    data = kb.load()
    for topic_data in data.values():
        papers = topic_data.get("papers", [])
        for paper in papers:
            if paper["id"] == target:
                if "review" not in paper:
                    raise PublishError([f"`{target}` 是人工整理的條目，不能用 unpublish 撤下"])
                papers.remove(paper)
                _drop_references(data, target)
                _check(data, kb, frozenset({paper["file"]}) if paper.get("file") else frozenset())
                if paper.get("file"):
                    (kb.root / paper["file"]).unlink(missing_ok=True)
                if kb.news_json.exists():
                    news = json.loads(kb.news_json.read_text())
                    remaining = [story for story in news if story["paperId"] != target]
                    if remaining != news:
                        kb.news_json.write_text(json.dumps(remaining, ensure_ascii=False, indent=2))
                kb.save(data)
                return f"paper {target}"
            for c in paper.get("commentary", []):
                if target in (c.get("doi"), c.get("pmid")):
                    if "review" not in c:
                        raise PublishError([f"`{target}` 是人工整理的評論，不能用 unpublish 撤下"])
                    paper["commentary"].remove(c)
                    if not paper["commentary"]:
                        del paper["commentary"]
                    kb.save(data)
                    return f"commentary {target} on {paper['id']}"
    raise PublishError([f"找不到 `{target}`"])


def evidence_markdown(paper: dict) -> str:
    """Provenance table for commit messages and comments."""
    return evidence_table_markdown(check_evidence(paper.get("ai_evidence") or [], paper.get("abstract", "")))
