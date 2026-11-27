"""An admin's review and unpublish buttons on the site (E6 #159, ADR-0021).

The API may not write content: one content writer applies every change through publish.py (ADR-0021). So the API
only records the request in app.content_requests and starts the content-requests Cloud Run job, which applies it and
fills in the outcome. The job takes no arguments; it reads every pending row. If the job cannot be started (or
CONTENT_REQUESTS_JOB is unset, as in development), the row waits for the job's next run, and the answer says so.
"""

import logging
from typing import Annotated, Any, Literal

import requests
from fastapi import APIRouter, Depends, Query, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from guthub_api.accounts import require_admin
from guthub_api.auth import User
from guthub_api.comments import PRIVATE
from guthub_api.db import Conn, get_conn

router = APIRouter()
logger = logging.getLogger("guthub_api.content_requests")

type Db = Annotated[Conn, Depends(get_conn)]
type Admin = Annotated[User, Depends(require_admin)]

METADATA_TOKEN = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
TIMEOUT = 10

_LEGACY_ACTIONS = ("review", "unpublish")
_NEWS_EVENT_ACTIONS = ("approve", "reject", "withdraw", "revise")


class ContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["review", "unpublish", "approve", "reject", "withdraw", "revise"]
    kind: Literal["paper", "news", "news_event"]
    target: str = Field(min_length=1, max_length=200, pattern=r"^\S(.*\S)?$")
    reason: str | None = Field(default=None, min_length=1, max_length=500)
    payload: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_kind_action_pair(self) -> "ContentRequest":
        if self.kind == "news_event" and self.action not in _NEWS_EVENT_ACTIONS:
            raise ValueError("news_event only supports approve, reject, withdraw, or revise")
        if self.kind in ("paper", "news") and self.action not in _LEGACY_ACTIONS:
            raise ValueError("paper/news only support review or unpublish")
        return self


def start_job(job: str | None) -> bool:
    """Run the job as this service's own account (Cloud Run metadata server); False if it could not be started."""
    if not job:
        return False
    try:
        token = requests.get(METADATA_TOKEN, headers={"Metadata-Flavor": "Google"}, timeout=TIMEOUT)
        token.raise_for_status()
        run = requests.post(
            f"https://run.googleapis.com/v2/{job}:run",
            headers={"Authorization": f"Bearer {token.json()['access_token']}"},
            timeout=TIMEOUT,
        )
        run.raise_for_status()
    except requests.RequestException:
        logger.exception("could not start %s", job)
        return False
    return True


@router.post("/admin/content-requests", status_code=202)
def request_change(body: ContentRequest, admin: Admin, db: Db, request: Request, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    payload: dict[str, Any] = dict(body.payload or {})
    if body.reason:
        payload["reason"] = body.reason
    row = db.execute(
        "insert into app.content_requests (action, kind, target, requested_by, payload)"
        " values (%s, %s, %s, %s, %s) returning id",
        (body.action, body.kind, body.target, admin.id, Jsonb(payload)),
    ).fetchone()
    assert row is not None
    started = start_job(request.app.state.settings.content_requests_job)
    return {"id": row["id"], "started": started}


@router.get("/admin/news-events")
def list_admin_news_events(
    admin: Admin,
    db: Db,
    response: Response,
    status: Annotated[Literal["draft", "pending_review", "published", "rejected", "withdrawn"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """Admin-only Newsroom review queue (N5 #290, ADR-0031). Reads view only; never writes content tables."""
    del admin
    response.headers.update(PRIVATE)
    if status:
        rows = db.execute(
            "select * from app.admin_news_review_queue where status = %s order by updated_at desc, id limit %s",
            (status, limit),
        ).fetchall()
    else:
        rows = db.execute(
            "select * from app.admin_news_review_queue"
            " order by case status when 'pending_review' then 0 when 'draft' then 1 when 'published' then 2 else 3 end,"
            " updated_at desc, id limit %s",
            (limit,),
        ).fetchall()
    items = [
        {
            "id": r["id"],
            "category": r["category"],
            "geography": r["geography"],
            "evidenceStatus": r["evidence_status"],
            "riskTier": r["risk_tier"],
            "status": r["status"],
            "reviewStatus": r["review_status"],
            "eventDate": r["event_date"].isoformat() if r["event_date"] else None,
            "publishedAt": r["published_at"].isoformat(),
            "effectiveDate": r["effective_date"].isoformat() if r["effective_date"] else None,
            "revisionNumber": r["revision_number"],
            "headline": r["headline"],
            "whatHappened": r["what_happened"],
            "whyItMatters": r["why_it_matters"],
            "clinicalRelevance": r["clinical_relevance"],
            "evidenceLimitations": r["evidence_limitations"],
            "correctionNote": r["correction_note"],
            "primaryDomain": r["primary_domain"],
            "secondaryDomains": list(r["secondary_domains"] or []),
            "sources": list(r["sources"] or []),
            "claims": list(r["claims"] or []),
        }
        for r in rows
    ]
    return {"items": items}
