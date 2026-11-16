"""Move the content authority between the JSON files and PostgreSQL (E2 #73, ADR-0021).

python content_writer.py status   --database-url URL
python content_writer.py cutover  --database-url URL          # JSON frozen, the database becomes the writer
python content_writer.py rollback --database-url URL          # back to JSON: the database content is exported first
python content_writer.py export   --database-url URL --out DIR  # one-way copy in the repository layout

URL may come from GUTHUB_IMPORT_DATABASE_URL; it needs the role that owns the app tables. Before cutover, stop every
JSON writer (the Paper Watch, accept and unpublish workflows) and import the final JSON with import_content.py.
cutover then refuses unless the database holds exactly what the JSON holds, records that manifest as the watermark,
and writes data/WRITER=postgres, which must be committed so the JSON writers refuse from then on.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from import_content import ROOT, WriterError, build_rows, check_writer, export_kb, manifest

WRITER_FILE = "data/WRITER"
LOCK = "select pg_advisory_xact_lock(hashtext('guthub-content-writer'))"


class CutoverError(RuntimeError):
    pass


def _set_flag(root: Path, writer: str) -> None:
    (root / WRITER_FILE).write_text(f"{writer}\n", encoding="utf-8")


def _flag(root: Path) -> str:
    path = root / WRITER_FILE
    return path.read_text(encoding="utf-8").strip() if path.exists() else "json"


def cutover(conn: Any, root: Path = ROOT) -> dict[str, Any]:
    """Make the database the content writer. Returns the watermark (the manifest both sides agreed on)."""
    if _flag(root) != "json":
        raise CutoverError(f"{WRITER_FILE} says {_flag(root)!r}; cutover starts from the JSON writer")
    source = build_rows(root)
    if source.errors:
        raise CutoverError("the JSON does not import cleanly: " + "; ".join(source.errors))
    watermark = manifest(source)
    with conn.transaction():
        conn.execute(LOCK)
        check_writer(conn, "json")
        with tempfile.TemporaryDirectory(prefix="guthub-cutover-") as tmp:
            export_kb(conn, Path(tmp))
            stored = manifest(build_rows(Path(tmp)))
        differing = [t for t in watermark["tables"] if watermark["tables"][t] != stored["tables"].get(t)]
        if differing:
            raise CutoverError(
                f"the database differs from the JSON in {', '.join(differing)}; run import_content.py, then cutover"
            )
        conn.execute(
            "update app.content_writer set writer = 'postgres', watermark = %s, changed_at = now()",
            (json.dumps(watermark),),
        )
    _set_flag(root, "postgres")
    return watermark


def rollback(conn: Any, root: Path = ROOT) -> None:
    """Make the JSON files the writer again, starting from the database's current content."""
    with conn.transaction():
        conn.execute(LOCK)
        check_writer(conn, "postgres")
        export_kb(conn, root)
        conn.execute("update app.content_writer set writer = 'json', watermark = null, changed_at = now()")
    _set_flag(root, "json")


def status(conn: Any, root: Path = ROOT) -> dict[str, Any]:
    writer, watermark, changed_at = conn.execute(
        "select writer, watermark, changed_at from app.content_writer"
    ).fetchone()
    events = conn.execute("select key, summary, created_at from app.publish_events order by created_at desc limit 5")
    return {
        "database": writer,
        "file": _flag(root),
        "changedAt": changed_at.isoformat(),
        "watermarkSources": (watermark or {}).get("sources"),
        "recentEvents": [{"key": k, "summary": s, "at": t.isoformat()} for k, s, t in events.fetchall()],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["status", "cutover", "rollback", "export"])
    parser.add_argument("--database-url", default=os.environ.get("GUTHUB_IMPORT_DATABASE_URL"))
    parser.add_argument("--out", type=Path, help="export target directory")
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("--database-url (or GUTHUB_IMPORT_DATABASE_URL) is required")
    if args.command == "export" and not args.out:
        parser.error("export needs --out")

    import psycopg

    with psycopg.connect(args.database_url) as conn:
        try:
            if args.command == "status":
                print(json.dumps(status(conn), indent=2, ensure_ascii=False))
            elif args.command == "cutover":
                cutover(conn)
                print(f"The database is the content writer. Commit {WRITER_FILE} so the JSON writers stop.")
            elif args.command == "rollback":
                rollback(conn)
                print(f"JSON is the content writer again. Review and commit data/, docs/ and {WRITER_FILE}.")
            else:
                export_kb(conn, args.out)
                print(f"exported to {args.out}")
        except (CutoverError, WriterError) as exc:
            print(f"Nothing changed: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
