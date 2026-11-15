"""Number provenance for AI classifications, and the auto-publish gate (ADR-0013).

The model reports where each number came from (``evidence``); nothing here trusts
that report. Abstract quotes are checked against the abstract text, and every
number in the KB entry must also appear in the abstract itself. Only papers that
pass every check are published without a human; the rest go to a review issue.
"""

import re
from dataclasses import asdict, dataclass
from typing import Literal

AbstractStatus = Literal["full", "truncated", "missing"]
EvidenceStatus = Literal["verified", "not_found", "web", "inference", "invalid"]

_SETUP_LABELS = {"BACKGROUND", "INTRODUCTION", "OBJECTIVE", "OBJECTIVES", "PURPOSE", "AIM", "AIMS", "METHODS"}
_RESULT_LABELS = {"RESULTS", "FINDINGS"}
_LABEL = re.compile(r"(?:^|\s)([A-Z][A-Z ]*[A-Z]):")
_REGISTRATION_END = re.compile(r"(NCT\d{8}|ChiCTR\w+|ISRCTN\d+|CRD\d+)\W*$")
_SENTENCE_END = (".", "!", "?", ")", "]", "。", "）", "」", '"', "'")

# Fields of a KB entry whose numbers must be traceable to the abstract.
CHECKED_FIELDS = ("n", "result", "bottomLine")


def abstract_status(abstract: str) -> AbstractStatus:
    """Classify an abstract as full, truncated, or missing.

    Truncated: a structured abstract with setup sections but no results section,
    or text that stops mid-sentence (registration numbers may end without a period).
    """
    text = (abstract or "").strip()
    if not text:
        return "missing"
    labels = set(_LABEL.findall(text))
    if labels & _SETUP_LABELS and not labels & _RESULT_LABELS:
        return "truncated"
    if text.endswith(_SENTENCE_END) or _REGISTRATION_END.search(text):
        return "full"
    return "truncated"


def _canonical(number: str) -> str:
    whole, _, frac = number.replace(",", "").partition(".")
    whole = whole.lstrip("0") or "0"
    frac = frac.rstrip("0")
    return f"{whole}.{frac}" if frac else whole


_CI = re.compile(r"\d+(?:[.·]\d+)?\s*%\s*CI", re.IGNORECASE)
# Digits glued to a letter on the left are labels, not values: G3, NCT…, C2D15; so are
# trial names (STELLAR-303, NICHE-2). A trailing "L" marks a line of therapy (1L, 2L).
_NUMBER = re.compile(
    r"(?<![A-Za-z\d.,·])(?<![A-Za-z]-)\d{1,3}(?:,\d{3})+(?![\d.])"
    r"|(?<![A-Za-z\d.·])(?<![A-Za-z]-)\d+(?:[.·]\d+)?(?![\dLl])"
)


def numbers_in(text: str) -> set[str]:
    """Canonical numbers in ``text``; ignores CI levels ("95% CI") and labels like G3 or 2L."""
    cleaned = _CI.sub("CI", text or "")
    return {_canonical(m.replace("·", ".")) for m in _NUMBER.findall(cleaned)}


def _norm_text(text: str) -> str:
    for a, b in (("·", "."), ("–", "-"), ("—", "-"), ("−", "-"), ("\u2009", " "), ("\xa0", " ")):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass
class EvidenceCheck:
    claim: str
    source: str
    quote: str | None
    url: str | None
    status: EvidenceStatus


def check_evidence(evidence: list[dict], abstract: str) -> list[EvidenceCheck]:
    """Verify each evidence item. Abstract quotes must be literal substrings of the abstract."""
    norm_abstract = _norm_text(abstract or "")
    checks = []
    for e in evidence:
        source, quote, url = e.get("source", ""), e.get("quote"), e.get("url")
        status: EvidenceStatus
        if source == "abstract":
            status = "verified" if quote and _norm_text(quote) in norm_abstract else "not_found"
        elif source == "web_fetch":
            status = "web" if url else "invalid"
        elif source == "inference":
            status = "inference"
        else:
            status = "invalid"
        checks.append(EvidenceCheck(e.get("claim", ""), source, quote, url, status))
    return checks


def entry_text(entry: dict) -> str:
    """The checked fields of a KB entry, joined for number extraction."""
    return " ".join(str(entry.get(k) or "") for k in CHECKED_FIELDS)


def numbers_not_in_abstract(text: str, abstract: str) -> list[str]:
    return sorted(numbers_in(text) - numbers_in(abstract), key=float)


def unsourced_numbers(text: str, evidence: list[dict]) -> list[str]:
    """Numbers in ``text`` that no evidence claim covers."""
    claimed = set().union(*(numbers_in(e.get("claim", "")) for e in evidence)) if evidence else set()
    return sorted(numbers_in(text) - claimed, key=float)


@dataclass
class GateResult:
    passed: bool
    reasons: list[str]


_STATUS_LABELS = {"not_found": "摘要中找不到", "web": "來自網頁", "inference": "推論", "invalid": "出處格式錯誤"}


def evaluate_paper_gate(paper: dict, auto_topics: set[str]) -> GateResult:
    """Every condition must hold for a paper to publish without human review."""
    reasons = []
    if paper.get("ai_parse_failed"):
        reasons.append("AI 分類失敗")
    status = paper.get("abstract_status") or abstract_status(paper.get("abstract", ""))
    if status != "full":
        reasons.append("摘要被截斷" if status == "truncated" else "摘要缺失")
    if paper.get("topic") not in auto_topics:
        reasons.append(f"topic `{paper.get('topic')}` 不支援自動發布")

    entry = paper.get("ai_suggested_js") or {}
    evidence = paper.get("ai_evidence") or []
    if not entry:
        reasons.append("沒有建議的 KB 條目")
    if not evidence:
        reasons.append("沒有數字出處")
    for c in check_evidence(evidence, paper.get("abstract", "")):
        if c.status != "verified":
            reasons.append(f"出處未通過（{_STATUS_LABELS[c.status]}）：{c.claim}")

    text = entry_text(entry)
    missing = numbers_not_in_abstract(text, paper.get("abstract", ""))
    if missing:
        reasons.append(f"KB 條目中這些數字在摘要裡找不到：{', '.join(missing)}")
    unsourced = unsourced_numbers(text, evidence)
    if unsourced:
        reasons.append(f"KB 條目中這些數字沒有附出處：{', '.join(unsourced)}")
    return GateResult(not reasons, reasons)


def evaluate_commentary_gate(proposal, abstract: str) -> GateResult:
    """Commentary publishes without review only when PubMed itself links it to the trial."""
    reasons = []
    if proposal.match_method != "comment_on":
        reasons.append("對應試驗由 AI 判斷，不是 PubMed CommentOn 連結")
    if proposal.new_data:
        reasons.append("含新數據，可能需要更新試驗卡片")
    missing = numbers_not_in_abstract(proposal.summary, abstract)
    if missing:
        reasons.append(f"摘要句中這些數字在原文找不到：{', '.join(missing)}")
    return GateResult(not reasons, reasons)


_ICONS = {"verified": "✓ 摘要中找到", "not_found": "✗ 摘要中找不到", "web": "🔗 網頁", "inference": "⚠ 推論"}


def _cell(text: str | None) -> str:
    return (text or "—").replace("|", "\\|").replace("\n", " ")


def evidence_table_markdown(checks: list[EvidenceCheck]) -> str:
    if not checks:
        return "_AI 沒有提供數字出處。_"
    rows = ["| 數字 | 來源 | 原文片段 / URL | 核對 |", "|---|---|---|---|"]
    for c in checks:
        ref = c.url if c.source == "web_fetch" else c.quote
        rows.append(f"| {_cell(c.claim)} | {_cell(c.source)} | {_cell(ref)} | {_ICONS.get(c.status, '✗ 格式錯誤')} |")
    return "\n".join(rows)


def checks_as_dicts(checks: list[EvidenceCheck]) -> list[dict]:
    return [asdict(c) for c in checks]
