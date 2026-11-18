"""Where Paper Watch writes published content: the JSON files in git, or PostgreSQL after cutover (E2 #73, ADR-0021).

Callers open a session for one request and run the unchanged publish.py functions on `session.kb`:

    with content_session("publish_paper", target=paper_id) as session:
        if session.done is None:
            session.record(summarize(publish_paper(paper, "auto", today, **session.kb_args)))

JSON mode (default): `session.kb` is the repository, and the workflow commits the files. It refuses once
data/WRITER says the database took over.

Database mode (GUTHUB_CONTENT_DATABASE_URL set): inside one transaction that holds the global content-writer lock,
the database's public content is exported to a temporary directory in the repository layout; publish.py edits and
validates it there; then the B4 importer writes the result back (an unpublished paper becomes withdrawn, never
deleted) and the request is recorded in app.publish_events. Any error rolls everything back. A request whose key
is already recorded (a retried workflow run) does nothing and reports what it did the first time.
"""

import os
import sys
import tempfile
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from publish import KB, ROOT, WRITER_FILE, PublishError, json_writer_active

Action = Literal["publish_paper", "publish_commentary", "unpublish", "review", "summarize"]
DATABASE_ENV = "GUTHUB_CONTENT_DATABASE_URL"


def _importer() -> Any:
    """import_content lives at the repository root, next to sitegen; scripts run from scripts/."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import import_content

    return import_content


def event_key(action: Action, target: str) -> str:
    """Names one request. A re-run of the same GitHub Actions run reuses GITHUB_RUN_ID, so retries share the key."""
    run = os.environ.get("GITHUB_RUN_ID") or f"local-{uuid.uuid4()}"
    return f"{action}:{target}:{run}"


@dataclass
class Session:
    #: The KB to pass to publish.py, or None in JSON mode (publish.py then uses the repository, its default).
    kb: KB | None
    #: Summary recorded by an earlier attempt of this request, or None if this attempt must do the work.
    done: str | None = None
    summary: str | None = field(default=None, init=False)

    @property
    def kb_args(self) -> dict[str, KB]:
        """Keyword arguments for publish.py: none in JSON mode, so its default (or a test's patch) applies."""
        return {} if self.kb is None else {"kb": self.kb}

    def record(self, summary: str) -> str:
        self.summary = summary
        return summary


@contextmanager
def content_session(action: Action, target: str, *, key: str | None = None, conn: Any = None) -> Generator[Session]:
    url = os.environ.get(DATABASE_ENV)
    if conn is None and not url:
        if not json_writer_active():
            raise PublishError(["內容已改由資料庫寫入（data/WRITER），JSON writer 已凍結；請設定 " + DATABASE_ENV])
        yield Session(None)
        return
    yield from _database_session(conn, url, action, key or event_key(action, target))


def _database_session(conn: Any, url: str | None, action: Action, key: str) -> Generator[Session]:
    import psycopg

    importer = _importer()
    own = conn is None
    connection = psycopg.connect(url) if own else conn  # type: ignore[arg-type]
    try:
        with connection.transaction():
            # One content writer at a time on every machine; the export below then sees all earlier writes.
            connection.execute("select pg_advisory_xact_lock(hashtext('guthub-content-writer'))")
            try:
                importer.check_writer(connection, "postgres")
            except importer.WriterError as exc:
                raise PublishError([str(exc)]) from exc
            row = connection.execute("select summary from app.publish_events where key = %s", (key,)).fetchone()
            with tempfile.TemporaryDirectory(prefix="guthub-content-") as tmp:
                root = Path(tmp)
                (root / "data").mkdir()
                (root / WRITER_FILE).write_text("json\n", encoding="utf-8")  # the checkout is a private JSON copy
                if row is not None:
                    yield Session(KB(root=root), done=row[0])
                    return
                importer.export_kb(connection, root)
                session = Session(KB(root=root))
                yield session
                if session.summary is None:
                    raise PublishError(["發布流程沒有回報結果，已全部回復"])
                rows = importer.build_rows(root)
                if rows.errors:
                    raise PublishError(rows.errors)
                importer.apply(connection, rows, writer="postgres")
                connection.execute(
                    "insert into app.publish_events (key, action, summary) values (%s, %s, %s)",
                    (key, action, session.summary),
                )
    finally:
        if own:
            connection.close()
