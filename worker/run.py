"""Paper Watch as a Cloud Run job (E3 #76, ADR-0021).

python worker/run.py [main.py arguments, e.g. --daily or --topic mCRC-MSI-H --dry-run]

With GUTHUB_CONTENT_DATABASE_URL set, the job first exports the database's content into this container's data/ and
docs/: the agents read papers.json for their prompts and triage. That copy is read-only in practice: data/WRITER says
postgres, so the JSON writer refuses, and every publish goes through content_session into the database. Tracking
state is read and written in app.paper_watch_state (scripts/config.py).
"""

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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
    sys.argv = [str(scripts / "main.py"), *sys.argv[1:]]
    runpy.run_path(str(scripts / "main.py"), run_name="__main__")


if __name__ == "__main__":
    main()
