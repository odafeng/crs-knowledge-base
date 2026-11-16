"""Weekly activity for the maintainer (G10 #121): counts only, computed from records the site already keeps.

An active reader is an account that commented, liked or reported during the week (Asia/Taipei, weeks start on
Monday). Nothing is stored for this: no page views, no sign-in history, no per-reader list leaves the API. Readers who
only read while signed in are not counted, because Supabase keeps only each account's latest sign-in. Counts for old
weeks can drop later, when deleted comments lose their author after 90 days and purged accounts take their likes.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response

from guthub_api.accounts import require_admin
from guthub_api.auth import User
from guthub_api.comments import PRIVATE
from guthub_api.db import Conn, get_conn

router = APIRouter()

type Db = Annotated[Conn, Depends(get_conn)]
type Admin = Annotated[User, Depends(require_admin)]

WEEKS = 12
TIMEZONE = "Asia/Taipei"

# Each count is a scalar subquery over one table, so no join can multiply rows. Weeks run oldest first.
WEEKLY = """
with weeks as (
  select start, start + interval '1 week' as finish
  from generate_series(
    date_trunc('week', now() at time zone %(tz)s) - %(span)s * interval '1 week',
    date_trunc('week', now() at time zone %(tz)s),
    interval '1 week'
  ) as start
),
actions as (
  select author_id as account_id, created_at from app.comments where author_id is not null
  union all select account_id, created_at from app.comment_like_events
  union all select reporter_id, created_at from app.comment_reports
)
select
  w.start::date as week,
  (select count(distinct a.account_id) from actions a
    where a.created_at at time zone %(tz)s >= w.start and a.created_at at time zone %(tz)s < w.finish) as active_readers,
  (select count(*) from app.accounts x
    where x.created_at at time zone %(tz)s >= w.start and x.created_at at time zone %(tz)s < w.finish) as new_accounts,
  (select count(*) from app.comments c
    where c.created_at at time zone %(tz)s >= w.start and c.created_at at time zone %(tz)s < w.finish) as comments,
  (select count(*) from app.comment_likes l
    where l.created_at at time zone %(tz)s >= w.start and l.created_at at time zone %(tz)s < w.finish) as likes
from weeks w
order by w.start
"""


@router.get("/admin/stats/weekly")
def weekly_activity(admin: Admin, db: Db, response: Response) -> Any:
    response.headers.update(PRIVATE)
    rows = db.execute(WEEKLY, {"tz": TIMEZONE, "span": WEEKS - 1}).fetchall()
    return {
        "timezone": TIMEZONE,
        "weeks": [
            {
                "week": row["week"].isoformat(),
                "activeReaders": row["active_readers"],
                "newAccounts": row["new_accounts"],
                "comments": row["comments"],
                "likes": row["likes"],
            }
            for row in rows
        ],
    }
