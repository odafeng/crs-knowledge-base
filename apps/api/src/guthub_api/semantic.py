"""Natural-language search over papers, news and cards (H3 #125, ADR-0022).

The query is embedded with Voyage AI and compared with the passages scripts/search_index.py stored. It arrives in a
POST body so it stays out of request logs, and it is never stored or tied to an account. Results below MIN_SCORE are
dropped: a question the site has nothing on gets an empty list, not the least-bad passages. The month's tokens are
shared with the indexer; once they reach the cap the endpoint answers 503 and the site falls back to keyword search.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from guthub_api.db import Conn, get_conn

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
MODEL = "voyage-4"  # must match scripts/search_index.py: vectors of different models are not comparable
LIMIT = 8
TAIPEI = ZoneInfo("Asia/Taipei")

router = APIRouter()
type Db = Annotated[Conn, Depends(get_conn)]
type Embed = Callable[[str], tuple[list[float], int]]


def _printable(value: str) -> str:
    if any(ch < " " for ch in value):
        raise ValueError("must not contain control characters")
    return value


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200), AfterValidator(_printable)
    ]


def voyage(key: str) -> Embed:
    def embed(text: str) -> tuple[list[float], int]:
        response = requests.post(
            VOYAGE_URL,
            json={"input": [text], "model": MODEL, "input_type": "query", "output_dimension": 1024},
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"], int(data["usage"]["total_tokens"])

    return embed


def _month() -> str:
    return datetime.now(TAIPEI).date().replace(day=1).isoformat()


@router.post("/semantic-search")
def semantic_search(query: Query, db: Db, request: Request, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    settings = request.app.state.settings
    embed: Embed | None = request.app.state.embed
    if embed is None:
        raise HTTPException(status_code=503, detail="Semantic search is not configured")
    row = db.execute("select tokens from app.embedding_usage where month = %s", (_month(),)).fetchone()
    if row and row["tokens"] >= settings.search_monthly_tokens:
        raise HTTPException(status_code=503, detail="Semantic search is paused for the rest of the month")
    try:
        vector, tokens = embed(query.query)
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Semantic search is unavailable") from exc
    db.execute(
        "insert into app.embedding_usage (month, tokens) values (%s, %s)"
        " on conflict (month) do update set tokens = app.embedding_usage.tokens + excluded.tokens",
        (_month(), tokens),
    )
    literal = "[" + ",".join(repr(float(v)) for v in vector) + "]"
    rows = db.execute(
        "select kind, path, title, snippet, 1 - (embedding operator(extensions.<=>) %s::extensions.vector) as score"
        " from app.search_chunks order by embedding operator(extensions.<=>) %s::extensions.vector limit %s",
        (literal, literal, LIMIT),
    ).fetchall()
    return {
        "results": [
            {
                "kind": r["kind"],
                "path": r["path"],
                "title": r["title"],
                "snippet": r["snippet"],
                "score": round(float(r["score"]), 3),
            }
            for r in rows
            if r["score"] >= settings.search_min_score
        ]
    }
