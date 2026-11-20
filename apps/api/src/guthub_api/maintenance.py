"""Scheduled maintenance jobs (E3 #76), run as Cloud Run jobs from the API image.

python -m guthub_api.maintenance purge-deleted-authors
python -m guthub_api.maintenance announce-news
python -m guthub_api.maintenance line-daily [--dry-run] [--date YYYY-MM-DD]

purge-deleted-authors clears the private author mapping of comments and forum posts deleted more than 90 days ago and removes
accounts deleted that long ago (app.purge_deleted_authors, ADR-0017). The privacy policy promises this, so it runs
daily. announce-news pushes stories published in the last two days to subscribed browsers, each story once
(guthub_api.announce, C5 #95); it also needs GUTHUB_VAPID_PRIVATE_KEY and GUTHUB_VAPID_SUBJECT. Both connect as
guthub_api through GUTHUB_DATABASE_URL, like the API. line-daily broadcasts the day's pick to the GutHub LINE account
(guthub_api.line, G3 #114) with GUTHUB_LINE_CHANNEL_ACCESS_TOKEN; --dry-run prints it without sending. It runs at 07:00
and sends what went public the day before, since Paper Watch publishes at 16:00.
"""

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta

import psycopg

from guthub_api.announce import announce_news, web_push
from guthub_api.daily import TAIPEI
from guthub_api.line import broadcast_daily
from guthub_api.settings import Settings

logger = logging.getLogger("guthub_api.maintenance")

DUE = "deleted_at < now() - interval '90 days'"


def line_day(now: datetime) -> date:
    """The day line-daily reports on: the day before the run, so the 07:00 message carries the 16:00 papers (#114)."""
    return now.astimezone(TAIPEI).date() - timedelta(days=1)


def purge_deleted_authors(url: str) -> dict[str, int]:
    with psycopg.connect(url, autocommit=True) as conn, conn.transaction():
        comments = conn.execute(f"select count(*) from app.comments where author_id is not null and {DUE}").fetchone()
        posts = conn.execute(f"select count(*) from app.forum_posts where author_id is not null and {DUE}").fetchone()
        accounts = conn.execute(f"select count(*) from app.accounts where {DUE}").fetchone()
        conn.execute("select app.purge_deleted_authors()")
    return {
        "clearedCommentAuthors": comments[0] if comments else 0,
        "clearedForumAuthors": posts[0] if posts else 0,
        "removedAccounts": accounts[0] if accounts else 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job", choices=["purge-deleted-authors", "announce-news", "line-daily"])
    parser.add_argument("--dry-run", action="store_true", help="line-daily: print the message, send nothing")
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="line-daily: the day whose additions to send (default: yesterday, Taiwan)",
    )
    args = parser.parse_args(argv)
    settings = Settings()
    if settings.database_url is None:
        print("GUTHUB_DATABASE_URL is required", file=sys.stderr)
        return 1
    url = settings.database_url.get_secret_value()
    if args.job == "line-daily":
        token = settings.line_channel_access_token
        if token is None and not args.dry_run:
            print("GUTHUB_LINE_CHANNEL_ACCESS_TOKEN is required (or use --dry-run)", file=sys.stderr)
            return 1
        result = broadcast_daily(
            url,
            args.date or line_day(datetime.now(TAIPEI)),
            settings.site_origin,
            None if args.dry_run or token is None else token.get_secret_value(),
        )
    elif args.job == "announce-news":
        if settings.vapid_private_key is None or not settings.vapid_subject:
            print("GUTHUB_VAPID_PRIVATE_KEY and GUTHUB_VAPID_SUBJECT are required", file=sys.stderr)
            return 1
        result = announce_news(url, web_push(settings.vapid_private_key.get_secret_value(), settings.vapid_subject))
    else:
        result = purge_deleted_authors(url)
    # One JSON line, so Cloud Logging can parse it; no identifiers, only counts.
    print(json.dumps({"job": args.job, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
