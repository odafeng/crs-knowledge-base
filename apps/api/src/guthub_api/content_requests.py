"""An admin's review and unpublish buttons on the site (E6 #159, ADR-0021).

The API may not write content: one content writer applies every change through publish.py (ADR-0021). So the API
only records the request in app.content_requests and starts the content-requests Cloud Run job, which applies it and
fills in the outcome. The job takes no arguments; it reads every pending row. If the job cannot be started (or
CONTENT_REQUESTS_JOB is unset, as in development), the row waits for the job's next run, and the answer says so.
"""

import logging
from typing import Annotated, Any, Literal

import requests
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

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


class ContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["review", "unpublish"]
    kind: Literal["paper", "news"]
    target: str = Field(min_length=1, max_length=200, pattern=r"^\S(.*\S)?$")


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
    row = db.execute(
        "insert into app.content_requests (action, kind, target, requested_by) values (%s, %s, %s, %s) returning id",
        (body.action, body.kind, body.target, admin.id),
    ).fetchone()
    assert row is not None
    started = start_job(request.app.state.settings.content_requests_job)
    return {"id": row["id"], "started": started}
