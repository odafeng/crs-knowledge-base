"""Event Verification Gate, 4-tier Risk Policy, and Adversarial Defense (N4 #289, ADR-0031).

Leaves legacy newsroom/gate.py (paper-based news numeric gate) 100% untouched.

Checks enforced (all fail closed):
1. Primary source traceability & exact quote matching against backend-fetched source text.
2. Numeric fidelity (every stated number appears in verified source) + arm/order swap detection.
3. Three-date semantics (event_date vs published_at vs effective_date) & stale-news detection.
4. Regulatory jurisdiction boundary (FDA/EMA cannot be extrapolated to TFDA/Taiwan NHI).
5. Evidence status ceiling (preprint/press_release/registry/recruitment cannot claim standard-of-care/efficacy).
6. Security & adversarial defense (malicious HTML/XSS, prompt injection, SSRF/secret exfiltration directives).
7. Four-tier risk policy (low / medium / high / reject) with Pilot routing High & Medium 100% to human review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from newsroom.gate import numbers as extract_numbers

RiskTier = Literal["low", "medium", "high", "reject"]
RouteDecision = Literal["allow_auto_candidate", "human_review", "hold", "reject"]

_HTML_XSS_RE = re.compile(
    r"<\s*(script|iframe|object|embed|svg|img|style|link|meta)\b|\bon(?:error|load|click|mouseover)\s*=|javascript:",
    re.IGNORECASE,
)
_PROMPT_INJECTION_RE = re.compile(
    r"(ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?"
    r"|bypass\s+(?:the\s+)?(?:gate|review|policy|rules?)"
    r"|auto[-\s]?publish\s+(?:immediately|now)"
    r"|mark\s+(?:as\s+)?(?:human[-\s]?)?reviewed"
    r"|call\s+internal\s+url|169\.254\.169\.254|metadata\.google\.internal"
    r"|exfiltrat|leak\s+secrets?|ANTHROPIC_API_KEY|GUTHUB_CONTENT_DATABASE_URL"
    r"|忽略(?:所有|上述|先前)?(?:規則|指令)|直接發布|跳過審核|偽造已審核|呼叫內部網址|洩漏密鑰)",
    re.IGNORECASE,
)
_TW_APPROVAL_CLAIM_RE = re.compile(
    r"(TFDA\s*已核准|台灣已核准|衛福部已核准|健保已給付|已納入台灣健保|台灣健保給付已生效)",
    re.IGNORECASE,
)
_TW_SOURCE_RE = re.compile(r"\b(tfda|nhi|taiwan)\b|食藥署|健保署|衛福部|台灣", re.IGNORECASE)
_OVERCLAIM_RE = re.compile(
    r"(改寫(?:臨床)?指引|已成為(?:新)?標準治療|確立(?:新)?標準|證明因果療效|證實(?:臨床)?有效|FDA\s*已正式核准)",
    re.IGNORECASE,
)
_RECRUITMENT_EFFICACY_RE = re.compile(
    r"(顯著延長存活|證實療效|達到主要療效終點|降低死亡風險|有效改善預後|大幅提升存活)",
    re.IGNORECASE,
)
_BREAKING_CLAIM_RE = re.compile(r"(今日公布|昨日公布|最新突破|剛發表|本日最新)", re.IGNORECASE)
_ALREADY_EFFECTIVE_RE = re.compile(r"(已經生效|今日起已生效|現已正式實施)", re.IGNORECASE)
_VS_PAIR_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:個月|mo|months?|%|人)?\s*(?:vs\.?|對照|相較於|比)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class GateEvaluation:
    passed: bool
    risk_tier: RiskTier
    route: RouteDecision
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    security_flagged: bool = False


@dataclass(frozen=True)
class EventContext:
    category: str  # regulatory | guideline | trial | society | device | safety | clinical
    geography: str  # taiwan | us | eu | global
    evidence_status: str  # approved | guideline | peer_reviewed | conference | preprint | registry | press_release
    verified_source_urls: tuple[str, ...]
    verified_source_text: str
    today: date
    event_date: str | None = None
    published_at: str | None = None
    effective_date: str | None = None
    milestone_stage: str = "announcement"
    source_conflict: bool = False
    needs_manual_classification: bool = False
    untrusted_inputs: tuple[str, ...] = field(default_factory=tuple)


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower()


def _draft_full_text(draft: dict[str, Any]) -> str:
    parts = [
        str(draft.get(k) or "")
        for k in ("headline", "what_happened", "why_it_matters", "clinical_relevance", "evidence_limitations")
    ]
    for claim in draft.get("claims") or []:
        if isinstance(claim, dict):
            parts.append(str(claim.get("claim_text") or ""))
    return "\n".join(parts)


def _check_arm_swap(draft_text: str, source_text: str) -> str | None:
    """Detect inverted intervention-vs-control numeric pairs (same numbers, swapped arms)."""
    source_pairs: set[tuple[str, str]] = set()
    for a, b in _VS_PAIR_RE.findall(source_text):
        source_pairs.add((f"{float(a):g}", f"{float(b):g}"))
    if not source_pairs:
        return None
    for a, b in _VS_PAIR_RE.findall(draft_text):
        fa, fb = f"{float(a):g}", f"{float(b):g}"
        if fa != fb and (fb, fa) in source_pairs and (fa, fb) not in source_pairs:
            return f"possible arm swap: draft states {fa} vs {fb}, source states {fb} vs {fa}"
    return None


def evaluate_event_gate(
    draft: dict[str, Any],
    ctx: EventContext,
    *,
    pilot_mode: bool = True,
    auto_publish_enabled: bool = False,
    max_stale_days: int = 45,
) -> GateEvaluation:
    """Evaluate a drafted Newsroom event against clinical accuracy, risk tier, and security rules."""
    violations: list[str] = []
    warnings: list[str] = []
    security_flagged = False

    draft_text = _draft_full_text(draft)
    source_norm = _norm(ctx.verified_source_text)

    # 1. Security & adversarial checks (malicious HTML / XSS / prompt injection in draft OR untrusted inputs)
    if _HTML_XSS_RE.search(draft_text):
        security_flagged = True
        violations.append("security: draft contains disallowed HTML or XSS payload")
    if _PROMPT_INJECTION_RE.search(draft_text):
        security_flagged = True
        violations.append("security: draft contains prompt-injection or exfiltration directive")
    for raw_in in ctx.untrusted_inputs:
        if _PROMPT_INJECTION_RE.search(raw_in):
            security_flagged = True
            violations.append("security: untrusted input contains prompt-injection directive")
            break
        if _HTML_XSS_RE.search(raw_in):
            warnings.append("security: untrusted input contained raw HTML markup (stripped/flagged)")

    # 2. Source conflict contradiction check
    if ctx.source_conflict:
        violations.append("source_conflict: primary paper and press release contradict each other")

    # 3. Primary source traceability & claim-evidence verification
    claims = draft.get("claims") or []
    verified_url_set = set(ctx.verified_source_urls)
    if not claims or not isinstance(claims, list):
        violations.append("traceability: draft has no claims")
    else:
        for idx, claim in enumerate(claims):
            if not isinstance(claim, dict):
                violations.append(f"traceability: claims[{idx}] is not an object")
                continue
            quote = str(claim.get("evidence_quote") or "")
            url = str(claim.get("source_url") or "")
            if not url or url not in verified_url_set:
                violations.append(f"traceability: claims[{idx}].source_url not in verified primary sources")
            if not quote or _norm(quote) not in source_norm:
                violations.append(f"traceability: claims[{idx}].evidence_quote not found verbatim in verified source")

    # 4. Numeric fidelity & arm-swap detection
    source_nums = extract_numbers(ctx.verified_source_text)
    draft_nums = extract_numbers(draft_text)
    date_years = {
        d[:4] for d in (ctx.event_date, ctx.published_at, ctx.effective_date) if isinstance(d, str) and len(d) >= 4
    }
    unsupported_nums = sorted(draft_nums - source_nums - date_years, key=float)
    if unsupported_nums:
        violations.append(f"numbers: unsupported number(s) not in verified source: {', '.join(unsupported_nums)}")

    swap_err = _check_arm_swap(draft_text, ctx.verified_source_text)
    if swap_err:
        violations.append(f"arm_integrity: {swap_err}")

    # 5. Jurisdiction boundary (FDA/EMA cannot be extrapolated to TFDA/Taiwan NHI)
    if (
        ctx.geography != "taiwan"
        and _TW_APPROVAL_CLAIM_RE.search(draft_text)
        and not _TW_SOURCE_RE.search(ctx.verified_source_text)
    ):
        violations.append("jurisdiction: non-Taiwan source extrapolated to TFDA approval or Taiwan NHI coverage")

    # 6. Evidence status ceiling & trial recruitment vs efficacy
    if ctx.evidence_status in ("preprint", "press_release", "registry") and _OVERCLAIM_RE.search(draft_text):
        violations.append(
            f"evidence_ceiling: {ctx.evidence_status} source overclaimed as guideline/standard-of-care/approval"
        )
    if (ctx.evidence_status == "registry" or ctx.milestone_stage == "recruitment") and _RECRUITMENT_EFFICACY_RE.search(
        draft_text
    ):
        violations.append("evidence_ceiling: trial recruitment/registry entry claims clinical efficacy")

    # 7. Three-date semantics & stale conference news check
    if ctx.effective_date:
        try:
            eff = date.fromisoformat(ctx.effective_date[:10])
            if eff > ctx.today and _ALREADY_EFFECTIVE_RE.search(draft_text):
                violations.append(
                    f"date_semantics: future effective_date {ctx.effective_date} described as already effective"
                )
        except ValueError:
            violations.append(f"date_semantics: invalid effective_date {ctx.effective_date!r}")

    if ctx.event_date:
        try:
            ev_dt = date.fromisoformat(ctx.event_date[:10])
            age = (ctx.today - ev_dt).days
            if age > max_stale_days and _BREAKING_CLAIM_RE.search(draft_text):
                violations.append(f"stale_news: event_date {ctx.event_date} ({age}d old) framed as breaking news")
        except ValueError:
            violations.append(f"date_semantics: invalid event_date {ctx.event_date!r}")

    # 8. Determine 4-tier risk policy & routing (fail closed on any violation or security flag)
    if security_flagged or violations:
        return GateEvaluation(
            passed=False,
            risk_tier="reject",
            route="reject" if security_flagged else "hold",
            violations=tuple(violations),
            warnings=tuple(warnings),
            security_flagged=security_flagged,
        )

    risk_tier: RiskTier
    if ctx.category in ("regulatory", "safety") or ctx.geography == "taiwan":
        risk_tier = "high"
    elif (
        ctx.evidence_status in ("preprint", "conference", "press_release", "registry")
        or ctx.needs_manual_classification
        or bool(warnings)
    ):
        risk_tier = "medium"
    else:
        risk_tier = "low"

    if risk_tier in ("high", "medium") or pilot_mode or not auto_publish_enabled:
        route: RouteDecision = "human_review"
    else:
        route = "allow_auto_candidate"

    return GateEvaluation(
        passed=True,
        risk_tier=risk_tier,
        route=route,
        violations=(),
        warnings=tuple(warnings),
        security_flagged=False,
    )
