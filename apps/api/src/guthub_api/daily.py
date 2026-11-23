"""The daily pick (G2 #113): one item from what was added on a given day, shared by LINE, push and the home page.

Order: coverage or approval changes, then news, then papers; within a kind, reviewed entries before unreviewed ones.
A day with nothing new has no pick, so nobody is sent an empty message. Plain-language copy is preferred when present
(news `dek` + clinical significance section, or a paper's `summary` title/takeaway/meaning), falling back to the
entry's bottom line so every number shown can still be traced directly to a reviewed or labelled entry.
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
MEANING_HEADINGS = ("為什麼重要", "對臨床的意義")


@dataclass(frozen=True)
class Candidate:
    kind: Kind
    ident: str
    title: str
    conclusion: str
    path: str
    date: date
    unreviewed: bool
    meaning: str = ""


def _rank(c: Candidate) -> tuple[int, bool, str]:
    return (PRIORITY[c.kind], c.unreviewed, c.ident)


def choose(candidates: list[Candidate]) -> Candidate | None:
    if not candidates:
        return None
    return min(candidates, key=_rank)


def ranked(candidates: list[Candidate]) -> list[Candidate]:
    """All of a day's candidates in the order the pick is chosen from (G9 #120 lists them during a conference)."""
    return sorted(candidates, key=_rank)


def pick_text(pick: Candidate, origin: str) -> str:
    """Plain-language single-item briefing for LINE and push: title, key takeaway, clinical meaning, and link."""
    return item_text(pick, origin, detailed=True)


def item_text(pick: Candidate, origin: str, *, detailed: bool = False) -> str:
    """Plain-language summary of one candidate, preserving AI-unreviewed disclosure and direct link."""
    label = "【AI 未審】" if pick.unreviewed else ""
    url = f"{origin.rstrip('/')}{pick.path}"
    if detailed:
        lines = [f"{label}{pick.title}", "", f"重點：{pick.conclusion}"]
        if pick.meaning:
            lines.extend(["", f"臨床意義：{pick.meaning}"])
        lines.extend(["", f"閱讀完整整理：\n{url}"])
        return "\n".join(lines)
    lines = [f"▸ {label}{pick.title}", f"重點：{pick.conclusion}", url]
    return "\n".join(lines)


def _news_meaning(body: Any) -> str:
    if not isinstance(body, list):
        return ""
    for heading in MEANING_HEADINGS:
        for section in body:
            if isinstance(section, dict) and section.get("heading") == heading:
                text = str(section.get("text") or "").strip()
                if text:
                    return text
    return ""


def _paper_copy(row: dict[str, Any]) -> tuple[str, str, str, bool]:
    """Prefers a paper's plain-Chinese summary when present, falling back to regimen + bottom_line."""
    summary = row.get("summary")
    if isinstance(summary, dict):
        title = str(summary.get("title") or "").strip()
        takeaway = str(summary.get("takeaway") or "").strip()
        meaning = str(summary.get("meaning") or "").strip()
        if title and takeaway:
            unreviewed = row["review_status"] == "auto" or summary.get("reviewedAt") is None
            return title, takeaway, meaning, unreviewed
    return (
        f"{row['regimen']}（{row['journal']} {row['year']}）",
        row["bottom_line"],
        "",
        row["review_status"] == "auto",
    )


def collect(conn: Connection[Any], day: date) -> list[Candidate]:
    """News and papers that went public on `day`, by the same dates the site lists them with."""
    cur = conn.cursor(row_factory=dict_row)  # the API pool and the job may hand over connections with any row factory
    news = cur.execute(
        "select n.id, n.headline, n.dek, n.body, n.review_status, p.bottom_line"
        " from app.public_news n join app.public_papers p on p.id = n.paper_id where n.published_at = %s",
        (day,),
    ).fetchall()
    papers = cur.execute(
        "select p.id, p.slug, p.regimen, p.journal, p.year, p.bottom_line, p.review_status, p.summary"
        " from app.public_papers p"
        " where coalesce(p.review_published_at, p.added_at, p.reviewed_at) = %s",
        (day,),
    ).fetchall()
    paper_candidates: list[Candidate] = []
    for r in papers:
        title, conclusion, meaning, unreviewed = _paper_copy(r)
        paper_candidates.append(
            Candidate(
                "paper",
                r["id"],
                title,
                conclusion,
                f"/papers/{r['slug']}/",
                day,
                unreviewed,
                meaning,
            )
        )
    return [
        *(
            Candidate(
                "news",
                r["id"],
                "".join(r["headline"]),
                str(r.get("dek") or "").strip() or r["bottom_line"],
                f"/news/{r['id']}/",
                day,
                r["review_status"] == "auto",
                _news_meaning(r.get("body")),
            )
            for r in news
        ),
        *paper_candidates,
    ]


def latest_day(conn: Connection[Any], before: date) -> date | None:
    """The most recent day before `before` on which something was added."""
    row = (
        conn.cursor(row_factory=dict_row)
        .execute(
            "select max(day) as day from ("
            " select published_at as day from app.public_news where published_at < %(before)s"
            " union all select coalesce(review_published_at, added_at, reviewed_at) from app.public_papers"
            "  where coalesce(review_published_at, added_at, reviewed_at) < %(before)s) as days",
            {"before": before},
        )
        .fetchone()
    )
    return row["day"] if row else None


@router.get("/daily-pick")
def daily_pick(
    db: Db,
    response: Response,
    day: Annotated[date | None, Query(alias="date")] = None,
    recent: bool = False,
) -> dict[str, Any]:
    """The pick for `date` (default: today in Taiwan). With `recent`, a day with nothing new falls back to the latest
    earlier day that had something (the home page always shows one); the pick's own date says which day that was."""
    day = day or datetime.now(TAIPEI).date()
    response.headers["Cache-Control"] = PUBLIC_CACHE
    pick = choose(collect(db, day))
    if pick is None and recent and (earlier := latest_day(db, day)) is not None:
        pick = choose(collect(db, earlier))
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
