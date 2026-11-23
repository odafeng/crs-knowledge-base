"""The daily LINE broadcast (G3 #114, ADR-0022): the day's pick to every follower of the GutHub official account.

Runs as a Cloud Run job at 07:00 Taiwan time (maintenance line-daily) and sends the previous day's pick. Only days
with something new are sent, never a fallback to an older item, and at most once a day: the job claims the day in
app.line_broadcasts with a retry key before sending and reuses that key on every retry, so LINE refuses a second
delivery (it answers 409 for a key it has already accepted) even if the job died after LINE took the message but before
sent_at was recorded. Messages are counted per recipient against the account's monthly quota; going over makes LINE
answer 429 and the job fail, which the job-failure alert reports.

During a conference (G9 #120: the windows Paper Watch scans daily) the one message lists the day's additions instead of
picking one, up to ROUNDUP of them in the pick's order with a link to the rest; outside those windows it goes back to
the single pick on its own.
"""

import json
import urllib.error
import urllib.request
import uuid
from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row

from guthub_api.conference import season_on
from guthub_api.daily import Candidate, collect, item_text, pick_text, ranked

LINE_API = "https://api.line.me"
TIMEOUT = 30
HEADING = "GutHub 晨間摘要"
ROUNDUP = 5


def message(pick: Candidate, origin: str) -> str:
    return f"{HEADING}｜{pick.date.month} 月 {pick.date.day} 日\n\n{pick_text(pick, origin)}"


def roundup(season: str, day: date, picks: list[Candidate], origin: str) -> str:
    """The conference-season message: the day's additions in plain language, best first, with links."""
    parts = [
        f"GutHub｜{season} 期間速報（{day.month} 月 {day.day} 日）",
        *(item_text(pick, origin) for pick in picks[:ROUNDUP]),
    ]
    if len(picks) > ROUNDUP:
        parts.append(f"還有 {len(picks) - ROUNDUP} 則更新：\n{origin.rstrip('/')}/updates/")
    return "\n\n".join(parts)


def _broadcast(base: str, token: str, retry_key: str, text: str) -> int:
    request = urllib.request.Request(
        f"{base.rstrip('/')}/v2/bot/message/broadcast",
        data=json.dumps({"messages": [{"type": "text", "text": text}]}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Line-Retry-Key": retry_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def broadcast_daily(url: str, day: date, origin: str, token: str | None, base: str = LINE_API) -> dict[str, Any]:
    """Send the day's pick. Without a token it is a dry run: it shows the text and records nothing."""
    with psycopg.connect(url, autocommit=True) as conn:
        cur = conn.cursor(row_factory=dict_row)
        picks = ranked(collect(conn, day))
        if not picks:
            return {"status": "nothing-new"}
        pick, season = picks[0], season_on(day)
        text = roundup(season, day, picks, origin) if season else message(pick, origin)
        if token is None:
            return {"status": "dry-run", "text": text}
        cur.execute(
            "insert into app.line_broadcasts (day, retry_key, url) values (%s, %s, %s) on conflict (day) do nothing",
            (day, uuid.uuid4(), pick.path),
        )
        claim = cur.execute("select retry_key, sent_at from app.line_broadcasts where day = %s", (day,)).fetchone()
        assert claim is not None
        if claim["sent_at"] is not None:
            return {"status": "already-sent"}
        status = _broadcast(base, token, str(claim["retry_key"]), text)
        # 409: LINE already accepted this retry key, i.e. an earlier attempt went out.
        if status not in (200, 409):
            raise RuntimeError(f"LINE broadcast failed with HTTP {status}")
        cur.execute("update app.line_broadcasts set sent_at = now() where day = %s", (day,))
        return {"status": "sent", "url": pick.path}
