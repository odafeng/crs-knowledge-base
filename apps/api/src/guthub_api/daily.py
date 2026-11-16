"""The daily pick (G2 #113): one item from what was added on a given day, shared by LINE, push and the home page.

Order: coverage or approval changes, then news, then papers; within a kind, reviewed entries before unreviewed ones.
A day with nothing new has no pick, so nobody is sent an empty message. The conclusion is always an entry's existing
bottom line (for a story, the bottom line of the paper it reports), never new wording, so every number shown can be
traced to a reviewed or labelled entry. Coverage changes arrive with G5 (#116); until then only news and papers
qualify.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from psycopg import Connection
from psycopg.rows import dict_row

from guthub_api.content import PUBLIC_CACHE
from guthub_api.db import Conn, get_conn

router = APIRouter()

type Db = Annotated[Conn, Depends(get_conn)]
type Kind = Literal["regulatory", "news", "paper"]

TAIPEI = ZoneInfo("Asia/Taipei")
PRIORITY: dict[str, int] = {"regulatory": 0, "news": 1, "paper": 2}


@dataclass(frozen=True)
class Candidate:
    kind: Kind
    ident: str
    title: str
    conclusion: str
    path: str
    date: date
    unreviewed: bool


def choose(candidates: list[Candidate]) -> Candidate | None:
    if not candidates:
        return None
    return min(candidates, key=lambda c: (PRIORITY[c.kind], c.unreviewed, c.ident))


def pick_text(pick: Candidate, origin: str) -> str:
    """The fixed plain-text form for messages: title, one-line conclusion, link, date."""
    label = "【AI 未審】" if pick.unreviewed else ""
    return f"{label}{pick.title}\n{pick.conclusion}\n{origin.rstrip('/')}{pick.path}\n{pick.date.isoformat()}"


def collect(conn: Connection[Any], day: date) -> list[Candidate]:
    """News and papers that went public on `day`, by the same dates the site lists them with."""
    cur = conn.cursor(row_factory=dict_row)  # the API pool and the job may hand over connections with any row factory
    news = cur.execute(
        "select n.id, n.headline, n.review_status, p.bottom_line"
        " from app.public_news n join app.public_papers p on p.id = n.paper_id where n.published_at = %s",
        (day,),
    ).fetchall()
    papers = cur.execute(
        "select p.id, p.slug, p.regimen, p.journal, p.year, p.bottom_line, p.review_status from app.public_papers p"
        " where coalesce(p.review_published_at, p.added_at, p.reviewed_at) = %s",
        (day,),
    ).fetchall()
    return [
        *(
            Candidate(
                "news",
                r["id"],
                "".join(r["headline"]),
                r["bottom_line"],
                f"/news/{r['id']}/",
                day,
                r["review_status"] == "auto",
            )
            for r in news
        ),
        *(
            Candidate(
                "paper",
                r["id"],
                f"{r['regimen']}（{r['journal']} {r['year']}）",
                r["bottom_line"],
                f"/papers/{r['slug']}/",
                day,
                r["review_status"] == "auto",
            )
            for r in papers
        ),
    ]


@router.get("/daily-pick")
def daily_pick(db: Db, response: Response, day: Annotated[date | None, Query(alias="date")] = None) -> dict[str, Any]:
    """The pick for `date` (default: today in Taiwan), or null when nothing new was added that day."""
    day = day or datetime.now(TAIPEI).date()
    response.headers["Cache-Control"] = PUBLIC_CACHE
    pick = choose(collect(db, day))
    if pick is None:
        return {"date": day.isoformat(), "pick": None}
    return {
        "date": day.isoformat(),
        "pick": {
            "kind": pick.kind,
            "title": pick.title,
            "conclusion": pick.conclusion,
            "url": pick.path,
            "date": pick.date.isoformat(),
            "unreviewed": pick.unreviewed,
        },
    }
