"""Scheduled maintenance jobs (E3 #76), run as Cloud Run jobs from the API image.

python -m guthub_api.maintenance purge-deleted-authors

purge-deleted-authors clears the private author mapping of comments deleted more than 90 days ago and removes
accounts deleted that long ago (app.purge_deleted_authors, ADR-0017). The privacy policy promises this, so it runs
daily. It connects as guthub_api through GUTHUB_DATABASE_URL, like the API.
"""

import argparse
import json
import logging
import sys

import psycopg

from guthub_api.settings import Settings

logger = logging.getLogger("guthub_api.maintenance")

DUE = "deleted_at < now() - interval '90 days'"


def purge_deleted_authors(url: str) -> dict[str, int]:
    with psycopg.connect(url, autocommit=True) as conn, conn.transaction():
        comments = conn.execute(f"select count(*) from app.comments where author_id is not null and {DUE}").fetchone()
        accounts = conn.execute(f"select count(*) from app.accounts where {DUE}").fetchone()
        conn.execute("select app.purge_deleted_authors()")
    return {"clearedCommentAuthors": comments[0] if comments else 0, "removedAccounts": accounts[0] if accounts else 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job", choices=["purge-deleted-authors"])
    args = parser.parse_args(argv)
    settings = Settings()
    if settings.database_url is None:
        print("GUTHUB_DATABASE_URL is required", file=sys.stderr)
        return 1
    result = purge_deleted_authors(settings.database_url.get_secret_value())
    # One JSON line, so Cloud Logging can parse it; no identifiers, only counts.
    print(json.dumps({"job": args.job, **result}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
