"""Controlled Newsroom Publisher and independent feature flags (N5 #290, ADR-0031, ADR-0021).

Guarantees:
- Uses the single content-writer advisory transaction lock: pg_advisory_xact_lock(hashtext('guthub-content-writer')).
- Uses app.publish_events idempotency keys so retries, crashes, or concurrent runs never duplicate writes.
- Revisions are append-only: revise creates revision_number + 1 with correction_note, preserving full history.
- Every approve/reject/withdraw/revise action records an immutable audit row in app.news_review_actions.
- 4 independent feature flags default safely to OFF (especially NEWSROOM_AUTO_PUBLISH_ENABLED=false and NEWSROOM_NOTIFY_ENABLED=false).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

LOCK_SQL = "select pg_advisory_xact_lock(hashtext('guthub-content-writer'))"


class PublisherError(RuntimeError):
    """Raised when a review or publish action violates Newsroom invariants."""


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class NewsroomFlags:
    collect_enabled: bool = False
    draft_enabled: bool = False
    auto_publish_enabled: bool = False
    notify_enabled: bool = False

    @classmethod
    def from_env(cls) -> NewsroomFlags:
        return cls(
            collect_enabled=_flag("NEWSROOM_COLLECT_ENABLED", False),
            draft_enabled=_flag("NEWSROOM_DRAFT_ENABLED", False),
            auto_publish_enabled=_flag("NEWSROOM_AUTO_PUBLISH_ENABLED", False),
            notify_enabled=_flag("NEWSROOM_NOTIFY_ENABLED", False),
        )


def apply_review_action(
    conn: Any,
    *,
    event_id: str,
    action: str,
    actor_label: str,
    reason: str,
    idempotency_key: str,
    actor_id: Any = None,
    revision_payload: dict[str, Any] | None = None,
    flags: NewsroomFlags | None = None,
    revalidate_fn: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Apply approve / reject / withdraw / revise / auto_publish inside one locked, idempotent transaction."""
    if action not in ("approve", "reject", "withdraw", "revise", "auto_publish"):
        raise PublisherError(f"unsupported newsroom action: {action!r}")
    clean_reason = reason.strip()
    if not clean_reason:
        raise PublisherError("reason is required for all newsroom review actions")

    active_flags = flags or NewsroomFlags.from_env()
    if action == "auto_publish" and not active_flags.auto_publish_enabled:
        raise PublisherError("NEWSROOM_AUTO_PUBLISH_ENABLED is false; auto-publish is disabled")

    pub_action = f"news_{action}"
    changed_public = False

    with conn.transaction(), conn.cursor() as cur:
        cur.execute(LOCK_SQL)
        prior = cur.execute("select summary from app.publish_events where key = %s", (idempotency_key,)).fetchone()
        if prior is not None:
            return {"ok": True, "idempotent_replay": True, "summary": prior[0]}

        row = cur.execute(
            "select id, status, risk_tier, current_revision_id from app.news_events where id = %s for update",
            (event_id,),
        ).fetchone()
        if row is None:
            raise PublisherError(f"unknown news event: {event_id}")
        _, current_status, risk_tier, current_rev_id = row

        if action == "auto_publish" and risk_tier != "low":
            raise PublisherError(f"auto_publish refused for risk_tier={risk_tier!r}; only low-risk eligible")

        new_rev_id = current_rev_id

        if action in ("approve", "auto_publish"):
            review_state = "reviewed" if action == "approve" else "auto"
            cur.execute(
                "update app.news_events"
                " set status = 'published', review_status = %s,"
                " first_published_at = coalesce(first_published_at, now()),"
                " withdrawn_at = null, updated_at = now()"
                " where id = %s",
                (review_state, event_id),
            )
            audit_action = "approve"
            summary = f"{action} news_event {event_id}"
            changed_public = True

        elif action == "reject":
            cur.execute(
                "update app.news_events set status = 'rejected', updated_at = now() where id = %s",
                (event_id,),
            )
            audit_action = "reject"
            summary = f"reject news_event {event_id}"
            changed_public = current_status == "published"

        elif action == "withdraw":
            cur.execute(
                "update app.news_events set status = 'withdrawn', withdrawn_at = now(), updated_at = now()"
                " where id = %s",
                (event_id,),
            )
            audit_action = "withdraw"
            summary = f"withdraw news_event {event_id}"
            changed_public = True

        else:  # revise (append-only new revision; never overwrites historical revision)
            payload = revision_payload or {}
            correction_note = str(payload.get("correction_note") or clean_reason).strip()
            prev_rev = cur.execute(
                "select revision_number, headline, what_happened, why_it_matters, clinical_relevance,"
                " evidence_limitations, model_name from app.news_revisions where id = %s",
                (current_rev_id,),
            ).fetchone()
            if prev_rev is None:
                raise PublisherError(f"news event {event_id} has no current revision to revise")
            next_num = int(prev_rev[0]) + 1
            headline = str(payload.get("headline") or prev_rev[1]).strip()
            what_happened = str(payload.get("what_happened") or prev_rev[2]).strip()
            why_it_matters = str(payload.get("why_it_matters") or prev_rev[3]).strip()
            clinical_relevance = str(payload.get("clinical_relevance") or prev_rev[4]).strip()
            evidence_limitations = str(payload.get("evidence_limitations") or prev_rev[5]).strip()
            inserted = cur.execute(
                "insert into app.news_revisions"
                " (event_id, revision_number, headline, what_happened, why_it_matters, clinical_relevance,"
                "  evidence_limitations, correction_note, model_name, created_by)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
                (
                    event_id,
                    next_num,
                    headline,
                    what_happened,
                    why_it_matters,
                    clinical_relevance,
                    evidence_limitations,
                    correction_note,
                    prev_rev[6],
                    actor_label,
                ),
            ).fetchone()
            assert inserted is not None
            new_rev_id = inserted[0]
            # Carry forward verified claims onto the new revision unless explicit claims are provided.
            explicit_claims = payload.get("claims")
            if isinstance(explicit_claims, list) and explicit_claims:
                for claim in explicit_claims:
                    cur.execute(
                        "insert into app.news_claims (revision_id, claim_text, evidence_quote, source_url, verified)"
                        " values (%s, %s, %s, %s, %s)",
                        (
                            new_rev_id,
                            claim["claim_text"],
                            claim["evidence_quote"],
                            claim["source_url"],
                            bool(claim.get("verified", True)),
                        ),
                    )
            else:
                cur.execute(
                    "insert into app.news_claims (revision_id, claim_text, evidence_quote, source_url, verified)"
                    " select %s, claim_text, evidence_quote, source_url, verified"
                    " from app.news_claims where revision_id = %s",
                    (new_rev_id, current_rev_id),
                )
            cur.execute(
                "update app.news_events"
                " set current_revision_id = %s, review_status = 'revised', updated_at = now()"
                " where id = %s",
                (new_rev_id, event_id),
            )
            audit_action = "revise"
            summary = f"revise news_event {event_id} -> r{next_num}"
            changed_public = current_status == "published"

        cur.execute(
            "insert into app.news_review_actions (event_id, revision_id, actor_id, actor_label, action, reason)"
            " values (%s, %s, %s, %s, %s, %s)",
            (event_id, new_rev_id, actor_id, actor_label, audit_action, clean_reason),
        )
        cur.execute(
            "insert into app.publish_events (key, action, summary) values (%s, %s, %s)",
            (idempotency_key, pub_action, summary),
        )

    if changed_public and revalidate_fn is not None:
        revalidate_fn()

    return {"ok": True, "idempotent_replay": False, "summary": summary, "changed_public": changed_public}
