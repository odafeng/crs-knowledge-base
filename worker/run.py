"""Paper Watch as a Cloud Run job (E3 #76, ADR-0021).

python worker/run.py [main.py arguments, e.g. --daily or --topic mCRC-MSI-H --dry-run]
python worker/run.py --scheduled [--dry-run]   # the daily 16:00 schedule

--scheduled picks the scan the GitHub workflow used to pick by cron: the full scan on Tuesday and Friday (Taiwan time),
otherwise --daily, which scans only in conference season. One job and one schedule cover both.

With GUTHUB_CONTENT_DATABASE_URL set, the job first exports the database's content into this container's data/ and
docs/: the agents read papers.json for their prompts and triage. That copy is read-only in practice: data/WRITER says
postgres, so the JSON writer refuses, and every publish goes through content_session into the database. Tracking
state is read and written in app.paper_watch_state (scripts/config.py).
"""

import os
import runpy
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
FULL_SCAN_DAYS = {2, 5}  # Tuesday, Friday


def main_args(args: list[str], today: date) -> list[str]:
    if args[:1] != ["--scheduled"]:
        return args
    return ([] if today.isoweekday() in FULL_SCAN_DAYS else ["--daily"]) + args[1:]


def main() -> None:
    url = os.environ.get("GUTHUB_CONTENT_DATABASE_URL")
    if url:
        sys.path.insert(0, str(ROOT))
        import import_content
        import psycopg

        with psycopg.connect(url) as conn:
            import_content.export_kb(conn, ROOT)
        (ROOT / "data/WRITER").write_text("postgres\n", encoding="utf-8")
        print("worker: exported the database content for the agents' context", flush=True)
    scripts = ROOT / "scripts"
    os.chdir(scripts)
    sys.path.insert(0, str(scripts))
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    sys.argv = [str(scripts / "main.py"), *main_args(sys.argv[1:], today)]
    runpy.run_path(str(scripts / "main.py"), run_name="__main__")


if __name__ == "__main__":
    main()
