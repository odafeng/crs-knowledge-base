"""Natural-language search over papers, news and cards (H3 #125, ADR-0022).

The query is embedded with Voyage AI and compared with the passages scripts/search_index.py stored. It arrives in a
POST body so it stays out of request logs, and it is never stored or tied to an account. Results below the minimum
score are dropped: a question the site has nothing on gets an empty list, not the least-bad passages. Passages are
checked against the public views on every query, so withdrawn content disappears at once, not at the next index run.

Anyone may search, so spending is bounded twice: per client address per minute (429), and per month, where queries
reserve their tokens before calling Voyage and stop INDEXER_RESERVE short of the cap so the indexer always has room.
"""

import time
from collections import defaultdict, deque
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
RESERVE = 256  # tokens held per query before the call; a 200-character question embeds to far fewer
INDEXER_RESERVE = 1_000_000  # tokens per month queries may not touch; a full re-index takes about 50,000

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


class PerMinute:
    """Queries per client address in the last minute, per instance; Cloud Run's few instances bound the total."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._seen: defaultdict[str, deque[float]] = defaultdict(deque)

    def allow(self, client: str) -> bool:
        now = time.monotonic()
        seen = self._seen[client]
        while seen and now - seen[0] > 60:
            seen.popleft()
        if len(seen) >= self.limit:
            return False
        seen.append(now)
        if len(self._seen) > 10_000:  # forget idle addresses so the map cannot grow without bound
            for key in [k for k, v in self._seen.items() if not v or now - v[-1] > 60]:
                del self._seen[key]
        return True


def client_address(request: Request) -> str:
    # Cloud Run appends the caller's address to X-Forwarded-For; earlier entries come from the caller and can be forged.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.rsplit(",", 1)[-1].strip() or (request.client.host if request.client else "")


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
    if not request.app.state.search_limiter.allow(client_address(request)):
        raise HTTPException(status_code=429, detail="Too many searches; try again in a minute")
    # Reserve before calling Voyage, atomically, so concurrent queries cannot overrun the cap together.
    reserved = db.execute(
        "insert into app.embedding_usage as u (month, tokens) values (%s, %s) on conflict (month) do update"
        " set tokens = u.tokens + excluded.tokens where u.tokens + excluded.tokens <= %s returning tokens",
        (_month(), RESERVE, settings.search_monthly_tokens - INDEXER_RESERVE),
    ).fetchone()
    if reserved is None:
        raise HTTPException(status_code=503, detail="Semantic search is paused for the rest of the month")
    tokens = 0  # what the call cost; the reservation is settled to it whatever happens
    try:
        vector, tokens = embed(query.query)
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Semantic search is unavailable") from exc
    finally:
        db.execute(
            "update app.embedding_usage set tokens = greatest(tokens + %s, 0) where month = %s",
            (tokens - RESERVE, _month()),
        )
    literal = "[" + ",".join(repr(float(v)) for v in vector) + "]"
    rows = db.execute(
        "select kind, path, title, snippet, 1 - (embedding operator(extensions.<=>) %s::extensions.vector) as score"
        " from app.search_chunks c where c.kind = 'card'"
        " or (c.kind = 'paper' and exists (select 1 from app.public_papers p where p.id = c.ref))"
        " or (c.kind = 'news' and exists (select 1 from app.public_news n where n.id = c.ref))"
        " order by embedding operator(extensions.<=>) %s::extensions.vector limit %s",
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
