"""Editorial source verification, ranking, structured Traditional Chinese draft writer, and budget caps (N3 #288, ADR-0031).

Security & isolation invariants:
- Every external candidate (including ChatGPT News Radar intake) MUST have its primary URL re-fetched
  by our backend before drafting; external summaries are never trusted as factual evidence.
- Draft writer runs with zero DB-write, GitHub, or notification privileges (pure LLM/schema stage).
- Domain classification is validated strictly against contracts/taxonomy.json (Central Topic Registry):
  unknown domain hints or low-confidence cross-domain items route to manual classification hold instead
  of falling back to generic-CRS or inventing slugs.
- Hard caps: MONTHLY_BUDGET_USD = 20.0 (USD 15-20), MAX_DAILY_CANDIDATES = 10, MAX_DAILY_DRAFTS = 3.
- Leaves legacy scripts/news_writer.py 100% untouched.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from html import unescape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from taxonomy_registry import TaxonomyError, TaxonomyRegistry, load_registry  # noqa: E402

MONTHLY_BUDGET_USD = 20.0
MAX_DAILY_CANDIDATES = 10
MAX_DAILY_DRAFTS = 3
MIN_VERIFIED_TEXT_CHARS = 80
DEFAULT_DRAFT_MODEL = "claude-sonnet-4-5"

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_CRC_RE = re.compile(
    r"\b(colorectal|colon|rectal|anal|mcrc|crc|tme|tatme|cme|eras|esd|emr|eftr|lars|ibd|crohn|diverticulitis|hemorrhoid|fistula)\b"
    r"|大腸|直腸|結腸|肛門|內視鏡|造口|吻合|骨盆底",
    re.IGNORECASE,
)

DRAFT_TOOL_SCHEMA: dict[str, Any] = {
    "name": "submit_event_brief",
    "description": "Submit a structured Traditional Chinese Newsroom event brief with claim-evidence mapping.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "headline",
            "what_happened",
            "why_it_matters",
            "clinical_relevance",
            "evidence_limitations",
            "primary_domain",
            "secondary_domains",
            "classification_confidence",
            "claims",
        ],
        "properties": {
            "headline": {"type": "string", "minLength": 6, "maxLength": 120},
            "what_happened": {"type": "string", "minLength": 20},
            "why_it_matters": {"type": "string", "minLength": 20},
            "clinical_relevance": {"type": "string", "minLength": 20},
            "evidence_limitations": {"type": "string", "minLength": 10},
            "primary_domain": {"type": "string"},
            "secondary_domains": {"type": "array", "items": {"type": "string"}},
            "classification_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "claims": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["claim_text", "evidence_quote", "source_url"],
                    "properties": {
                        "claim_text": {"type": "string", "minLength": 5},
                        "evidence_quote": {"type": "string", "minLength": 5},
                        "source_url": {"type": "string", "pattern": "^https://"},
                    },
                },
            },
        },
    },
}


@dataclass(frozen=True)
class EditorialWeights:
    crs_relevance: float = 3.0
    clinical_importance: float = 3.0
    recency: float = 2.0
    taiwan_relevance: float = 2.5
    source_quality: float = 2.0


@dataclass(frozen=True)
class VerifiedSource:
    ok: bool
    canonical_url: str
    verified_text: str = ""
    rejection_reason: str | None = None


@dataclass(frozen=True)
class DraftResult:
    ok: bool
    candidate_key: str
    status: str  # drafted | held_classification | rejected | budget_stopped
    draft: dict[str, Any] | None = None
    estimated_cost_usd: float = 0.0
    reason: str | None = None


@dataclass
class BudgetGuard:
    monthly_spent_usd: float = 0.0
    monthly_cap_usd: float = MONTHLY_BUDGET_USD
    daily_candidates_processed: int = 0
    max_daily_candidates: int = MAX_DAILY_CANDIDATES
    daily_drafts_created: int = 0
    max_daily_drafts: int = MAX_DAILY_DRAFTS
    stopped_reason: str | None = None

    def can_process_candidate(self) -> bool:
        if self.monthly_spent_usd >= self.monthly_cap_usd:
            self.stopped_reason = (
                f"monthly budget cap reached (${self.monthly_spent_usd:.2f} >= ${self.monthly_cap_usd:.2f})"
            )
            return False
        if self.daily_candidates_processed >= self.max_daily_candidates:
            self.stopped_reason = (
                f"daily candidate cap reached ({self.daily_candidates_processed}/{self.max_daily_candidates})"
            )
            return False
        return True

    def can_draft(self) -> bool:
        if not self.can_process_candidate():
            return False
        if self.daily_drafts_created >= self.max_daily_drafts:
            self.stopped_reason = f"daily draft cap reached ({self.daily_drafts_created}/{self.max_daily_drafts})"
            return False
        return True

    def record_candidate(self) -> None:
        self.daily_candidates_processed += 1

    def record_draft(self, cost_usd: float) -> None:
        self.daily_drafts_created += 1
        self.monthly_spent_usd += max(0.0, cost_usd)


@dataclass
class BatchRunReport:
    status: str  # ok | budget_stopped
    selected_count: int
    drafts: list[DraftResult] = field(default_factory=list)
    stopped_reason: str | None = None


def extract_plain_source_text(raw_bytes: bytes) -> str:
    text = raw_bytes.decode("utf-8", errors="replace")
    text = _SCRIPT_STYLE_RE.sub(" ", text)
    text = unescape(_TAG_RE.sub(" ", text))
    return re.sub(r"\s+", " ", text).strip()


def verify_candidate_source(
    candidate: dict[str, Any],
    *,
    fetcher: Callable[[str], bytes],
) -> VerifiedSource:
    """Re-fetch primary URL on the backend; never trust external candidate summaries."""
    url = str(candidate.get("canonical_url") or "").strip()
    if not url.startswith("https://"):
        return VerifiedSource(ok=False, canonical_url=url, rejection_reason="non-https canonical_url")
    try:
        raw = fetcher(url)
    except Exception as exc:
        return VerifiedSource(ok=False, canonical_url=url, rejection_reason=f"primary source fetch failed: {exc}")
    plain = extract_plain_source_text(raw)
    if len(plain) < MIN_VERIFIED_TEXT_CHARS:
        return VerifiedSource(
            ok=False,
            canonical_url=url,
            rejection_reason=f"primary source text too short ({len(plain)} chars < {MIN_VERIFIED_TEXT_CHARS})",
        )
    return VerifiedSource(ok=True, canonical_url=url, verified_text=plain)


def score_candidate(
    candidate: dict[str, Any],
    *,
    today: date,
    weights: EditorialWeights = EditorialWeights(),
) -> float:
    title = str(candidate.get("title") or "")
    text = f"{title} {candidate.get('verified_source_text') or ''}"
    crs_score = 1.0 if _CRC_RE.search(text) else 0.0

    importance_map = {
        "regulatory": 1.0,
        "safety": 1.0,
        "guideline": 0.95,
        "trial": 0.8,
        "device": 0.65,
        "society": 0.6,
        "clinical": 0.55,
    }
    importance = importance_map.get(str(candidate.get("event_type") or "clinical").lower(), 0.4)

    recency = 0.3
    raw_date = candidate.get("published_at") or candidate.get("event_date")
    if isinstance(raw_date, str) and len(raw_date) >= 10:
        try:
            age_days = max(0, (today - date.fromisoformat(raw_date[:10])).days)
            recency = max(0.0, 1.0 - (age_days / 30.0))
        except ValueError:
            recency = 0.3

    taiwan = 1.0 if str(candidate.get("geography") or "").lower() == "taiwan" else 0.0
    tier_map = {"tier1": 1.0, "tier2": 0.7, "tier3": 0.4}
    quality = tier_map.get(str(candidate.get("trust_tier") or "tier2").lower(), 0.5)

    return round(
        crs_score * weights.crs_relevance
        + importance * weights.clinical_importance
        + recency * weights.recency
        + taiwan * weights.taiwan_relevance
        + quality * weights.source_quality,
        4,
    )


def select_candidates(
    candidates: list[dict[str, Any]],
    *,
    today: date,
    max_candidates: int = MAX_DAILY_CANDIDATES,
    max_per_domain: int = 3,
    weights: EditorialWeights = EditorialWeights(),
) -> list[dict[str, Any]]:
    """Rank verified candidates with CRS filter, weighted scoring, and per-domain diversity cap."""
    scored: list[tuple[float, dict[str, Any]]] = []
    for c in candidates:
        s = score_candidate(c, today=today, weights=weights)
        if not _CRC_RE.search(f"{c.get('title', '')} {c.get('verified_source_text', '')}"):
            continue
        scored.append((s, c))

    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("dedup_key") or pair[1].get("canonical_url") or "")))

    selected: list[dict[str, Any]] = []
    domain_counts: dict[str, int] = {}
    for score_val, cand in scored:
        if len(selected) >= max_candidates:
            break
        dom = str(cand.get("primary_domain_hint") or "_unhinted")
        if domain_counts.get(dom, 0) >= max_per_domain:
            continue
        domain_counts[dom] = domain_counts.get(dom, 0) + 1
        selected.append({**cand, "editorial_score": score_val})
    return selected


def validate_draft_schema(
    draft: dict[str, Any],
    registry: TaxonomyRegistry,
) -> tuple[bool, bool, list[str]]:
    """Validate structured draft fields, claim-evidence mapping, and registry domains.

    Returns (schema_ok, needs_manual_classification, errors).
    """
    errors: list[str] = []
    for req_field in ("headline", "what_happened", "why_it_matters", "clinical_relevance", "evidence_limitations"):
        val = draft.get(req_field)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"missing non-empty {req_field}")

    claims = draft.get("claims")
    if not isinstance(claims, list) or len(claims) == 0:
        errors.append("claims must be a non-empty list")
    else:
        for idx, claim in enumerate(claims):
            if not isinstance(claim, dict):
                errors.append(f"claims[{idx}] must be an object")
                continue
            for cf in ("claim_text", "evidence_quote", "source_url"):
                if not isinstance(claim.get(cf), str) or not claim[cf].strip():
                    errors.append(f"claims[{idx}] missing {cf}")
            url = str(claim.get("source_url") or "")
            if url and not url.startswith("https://"):
                errors.append(f"claims[{idx}].source_url must start with https://")

    primary = str(draft.get("primary_domain") or "").strip()
    secondaries = draft.get("secondary_domains") or []
    confidence = str(draft.get("classification_confidence") or "low").lower()
    needs_manual = False

    if (
        not primary
        or primary not in registry.active_domain_slugs
        or not isinstance(secondaries, list)
        or any(s not in registry.active_domain_slugs for s in secondaries)
    ):
        needs_manual = True
    else:
        try:
            registry.validate_assignment(primary_domain=primary, secondary_domains=list(secondaries))
        except TaxonomyError:
            needs_manual = True

    if confidence == "low":
        needs_manual = True

    return len(errors) == 0, needs_manual, errors


def build_draft_prompt(candidate: dict[str, Any], verified_text: str, registry: TaxonomyRegistry) -> str:
    domains_desc = "\n".join(f"- {d.slug}: {d.label_zh} ({d.label_en}) — {d.description_zh}" for d in registry.domains)
    return (
        "你是 GutHub 大腸直腸外科每日情報編輯。請嚴格依據下方已由後端重新抓取的原始來源文字，"
        "使用繁體中文撰寫結構化臨床短訊，並呼叫 submit_event_brief 工具提交。\n"
        "絕對禁止引用原始來源文字以外的數字、療效宣稱、核准範圍或外部摘要。\n"
        "每一個關鍵陳述都必須在 claims 中附上原文逐字摘錄（evidence_quote）與 source_url。\n\n"
        f"## 八大專科領域清單（僅能從此清單選擇，不可自造 slug）\n{domains_desc}\n\n"
        f"## 候選事件\n"
        f"- 標題：{candidate.get('title', '')}\n"
        f"- 來源 URL：{candidate.get('canonical_url', '')}\n"
        f"- 類型：{candidate.get('event_type', 'clinical')}\n"
        f"- 地區：{candidate.get('geography', 'global')}\n"
        f"- 領域提示（僅供參考，須以研究核心問題判斷）：{candidate.get('primary_domain_hint') or '無'}\n\n"
        f"## 後端驗證之原始來源全文（節錄上限 12000 字元）\n{verified_text[:12000]}\n"
    )


type ModelCaller = Callable[[str, dict[str, Any]], tuple[dict[str, Any], float]]


def anthropic_draft_caller(client: Any, *, model: str = DEFAULT_DRAFT_MODEL) -> ModelCaller:
    """Wrap an Anthropic SDK client into a pure ModelCaller returning (tool_input_dict, estimated_cost_usd)."""

    def _call(prompt: str, tool_schema: dict[str, Any]) -> tuple[dict[str, Any], float]:
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            tools=[tool_schema],
            tool_choice={"type": "tool", "name": tool_schema["name"]},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_input: dict[str, Any] = {}
        for block in getattr(resp, "content", []):
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_schema["name"]:
                tool_input = dict(getattr(block, "input", {}) or {})
                break
        usage = getattr(resp, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        # Conservative Sonnet-class estimate: $3/M input, $15/M output
        cost = (in_tok * 3.0 + out_tok * 15.0) / 1_000_000.0
        return tool_input, round(cost, 6)

    return _call


def run_editorial_batch(
    candidates: list[dict[str, Any]],
    *,
    today: date,
    fetcher: Callable[[str], bytes],
    model_caller: ModelCaller,
    budget: BudgetGuard,
    registry: TaxonomyRegistry | None = None,
) -> BatchRunReport:
    """Verify sources, rank, and draft up to daily/monthly caps with fail-closed classification holds."""
    reg = registry or load_registry()

    verified: list[dict[str, Any]] = []
    rejected_results: list[DraftResult] = []
    for cand in candidates:
        key = str(cand.get("dedup_key") or cand.get("canonical_url") or "")
        hint = cand.get("primary_domain_hint")
        # Unknown non-empty domain hints are preserved for audit, never coerced to generic-CRS.
        check = verify_candidate_source(cand, fetcher=fetcher)
        if not check.ok:
            rejected_results.append(
                DraftResult(ok=False, candidate_key=key, status="rejected", reason=check.rejection_reason)
            )
            continue
        verified.append({**cand, "verified_source_text": check.verified_text, "primary_domain_hint": hint})

    selected = select_candidates(verified, today=today, max_candidates=budget.max_daily_candidates)
    results: list[DraftResult] = list(rejected_results)
    stopped = False

    for cand in selected:
        key = str(cand.get("dedup_key") or cand.get("canonical_url") or "")
        if not budget.can_draft():
            stopped = True
            results.append(
                DraftResult(ok=False, candidate_key=key, status="budget_stopped", reason=budget.stopped_reason)
            )
            break

        budget.record_candidate()
        prompt = build_draft_prompt(cand, cand["verified_source_text"], reg)
        draft_payload, cost_usd = model_caller(prompt, DRAFT_TOOL_SCHEMA)
        budget.record_draft(cost_usd)

        schema_ok, needs_manual, errors = validate_draft_schema(draft_payload, reg)
        if not schema_ok:
            results.append(
                DraftResult(
                    ok=False,
                    candidate_key=key,
                    status="rejected",
                    draft=draft_payload,
                    estimated_cost_usd=cost_usd,
                    reason="; ".join(errors),
                )
            )
            continue

        # Also hold if the incoming hint was an unknown non-registry slug and model confidence wasn't high.
        incoming_hint = cand.get("primary_domain_hint")
        if incoming_hint and incoming_hint not in reg.active_domain_slugs:
            needs_manual = True

        results.append(
            DraftResult(
                ok=not needs_manual,
                candidate_key=key,
                status="held_classification" if needs_manual else "drafted",
                draft=draft_payload,
                estimated_cost_usd=cost_usd,
                reason="requires manual specialty classification" if needs_manual else None,
            )
        )

    return BatchRunReport(
        status="budget_stopped" if stopped else "ok",
        selected_count=len(selected),
        drafts=results,
        stopped_reason=budget.stopped_reason if stopped else None,
    )


def format_report_json(report: BatchRunReport) -> str:
    return json.dumps(
        {
            "status": report.status,
            "selected_count": report.selected_count,
            "stopped_reason": report.stopped_reason,
            "drafts": [
                {
                    "candidate_key": d.candidate_key,
                    "status": d.status,
                    "cost_usd": d.estimated_cost_usd,
                    "reason": d.reason,
                }
                for d in report.drafts
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
