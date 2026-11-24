"""The single content writer (E2 #73): JSON <-> PostgreSQL cutover, and publishing through the database.

Needs Supabase local with migrations (GUTHUB_TEST_DATABASE_URL); skips without it unless GUTHUB_REQUIRE_DB=1. Most
tests run inside a transaction that is rolled back; the concurrency test commits and restores the content afterwards.
"""

import json
import os
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path

import content_writer
import pytest
from import_content import WriterError, apply, build_rows, export_kb, manifest

from content_store import content_session
from publish import KB, PublishError, publish_paper, unpublish
from test_publish import TODAY, _paper
from validate import validate_data

ROOT = Path(__file__).resolve().parent.parent
DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")
if not DB_URL and os.environ.get("GUTHUB_REQUIRE_DB") != "1":
    pytest.skip("no test database", allow_module_level=True)

CONTENT = "app.topics, app.papers, app.paper_relations, app.research_commentary, app.news"


def copy_repo(tmp_path: Path) -> Path:
    for name in ("data", "docs"):
        shutil.copytree(ROOT / name, tmp_path / name)
    # The copy stands for the repository before cutover, whichever writer the real one has now.
    (tmp_path / "data/WRITER").write_text("json\n")
    return tmp_path


@pytest.fixture
def conn() -> Iterator:
    if not DB_URL:
        pytest.fail("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
    import psycopg

    with psycopg.connect(DB_URL) as connection, connection.transaction(force_rollback=True):
        connection.execute(f"truncate {CONTENT}, app.comments, app.comment_reports, app.moderation_events cascade")
        connection.execute("truncate app.publish_events, app.paper_watch_state")
        connection.execute("update app.content_writer set writer = 'json', watermark = null")
        apply(connection, build_rows(ROOT))
        yield connection


@pytest.fixture
def db_writer(conn, tmp_path):
    """The database after cutover from a copy of the repository."""
    content_writer.cutover(conn, copy_repo(tmp_path))
    return conn


def publish_auto(conn, key: str, **overrides) -> str:
    paper = _paper(**overrides)
    with content_session("publish_paper", paper["doi"], key=key, conn=conn) as session:
        if session.done is None:
            entry = publish_paper(paper, "auto", TODAY, **session.kb_args)
            session.record(f"publish {entry['id']}")
    return session.done or session.summary or ""


def count(conn, query: str, *params) -> int:
    return conn.execute(query, params).fetchone()[0]


# --- export and cutover -------------------------------------------------------------------------------------------


def test_export_reproduces_the_repository_content(conn, tmp_path):
    export_kb(conn, tmp_path)
    assert manifest(build_rows(tmp_path))["tables"] == manifest(build_rows(ROOT))["tables"]
    assert validate_data(json.loads((tmp_path / "data/papers.json").read_text()), tmp_path) == []


def test_cutover_refuses_when_the_database_differs(conn, tmp_path):
    root = copy_repo(tmp_path)
    raw = json.loads((root / "data/papers.json").read_text())
    next(p for block in raw.values() for p in block.get("papers", []))["result"] = "changed after the import"
    (root / "data/papers.json").write_text(json.dumps(raw, ensure_ascii=False))
    with pytest.raises(content_writer.CutoverError, match="papers"):
        content_writer.cutover(conn, root)
    assert count(conn, "select count(*) from app.content_writer where writer = 'json'") == 1
    assert (root / "data/WRITER").read_text().strip() == "json"


def test_cutover_hands_over_with_a_watermark(conn, tmp_path):
    root = copy_repo(tmp_path)
    watermark = content_writer.cutover(conn, root)
    writer, stored = conn.execute("select writer, watermark from app.content_writer").fetchone()
    assert writer == "postgres" and stored == watermark == manifest(build_rows(ROOT))
    assert (root / "data/WRITER").read_text().strip() == "postgres"
    # From now on the JSON import cannot overwrite the database, and a second cutover is refused.
    with pytest.raises(WriterError):
        apply(conn, build_rows(ROOT))
    with pytest.raises(content_writer.CutoverError):
        content_writer.cutover(conn, root)
    # Paper Watch's tracking state moved in with the content (E3 #76).
    stored = dict(conn.execute("select name, data from app.paper_watch_state").fetchall())
    assert stored["tracked-dois"] == json.loads((ROOT / "data/tracked-dois.json").read_text())


def test_the_frozen_json_writer_refuses_to_publish(tmp_path):
    root = copy_repo(tmp_path)
    (root / "data/WRITER").write_text("postgres\n")
    before = (root / "data/papers.json").read_text()
    with pytest.raises(PublishError, match="data/WRITER"):
        publish_paper(_paper(), "auto", TODAY, KB(root=root))
    assert (root / "data/papers.json").read_text() == before


def test_rollback_exports_the_database_and_hands_back(db_writer, tmp_path):
    publish_auto(db_writer, "k-rollback")
    root = tmp_path / "back"
    root.mkdir()
    (root / "data").mkdir()
    content_writer.rollback(db_writer, root)
    assert (root / "data/WRITER").read_text().strip() == "json"
    assert db_writer.execute("select writer from app.content_writer").fetchone()[0] == "json"
    papers = json.loads((root / "data/papers.json").read_text())
    assert any(p["id"] == "test-auto-2026" for block in papers.values() for p in block.get("papers", []))
    assert json.loads((root / "data/tracked-dois.json").read_text()) == json.loads(
        (ROOT / "data/tracked-dois.json").read_text()
    )


# --- publishing through the database ------------------------------------------------------------------------------


def test_database_mode_needs_the_cutover(conn):
    with pytest.raises(PublishError, match="not the authority yet"):
        publish_auto(conn, "k-early")
    assert count(conn, "select count(*) from app.papers where id = 'test-auto-2026'") == 0


def test_an_auto_paper_is_published_once_per_request(db_writer):
    summary = publish_auto(db_writer, "k-1")
    row = db_writer.execute(
        "select p.review_status, p.review_published_at, p.source, p.source_file, p.detail_html from app.papers p"
        " join app.public_papers using (id) where id = 'test-auto-2026'"
    ).fetchone()
    assert row[0] == "auto" and str(row[1]) == TODAY and row[2] == "abstract"
    assert row[3].startswith("docs/") and "<h" in row[4]  # the detail page is stored as HTML
    assert db_writer.execute("select summary from app.publish_events where key = 'k-1'").fetchone()[0] == summary
    # A retried run with the same key does nothing and reports the first result.
    assert publish_auto(db_writer, "k-1") == summary
    assert count(db_writer, "select count(*) from app.papers where id = 'test-auto-2026'") == 1
    assert count(db_writer, "select count(*) from app.publish_events") == 1


def test_robotic_surgery_paper_publishes_and_round_trips_export(db_writer, tmp_path):
    paper = _paper(id="color-iii-2026")
    paper["topic"] = "robotic-surgery"
    paper["doi"] = "10.1016/test-color-iii-db"
    paper["pmid"] = "99990999"
    paper["ai_suggested_filename"] = "COLOR_III_2026.html"
    with content_session("publish_paper", paper["doi"], key="k-robotic-1", conn=db_writer) as session:
        entry = publish_paper(paper, "auto", TODAY, **session.kb_args)
        session.record(f"publish {entry['id']}")
    assert (
        count(
            db_writer,
            "select count(*) from app.public_papers where id = 'color-iii-2026' and topic_key = 'robotic-surgery'",
        )
        == 1
    )
    out = tmp_path / "exported"
    export_kb(db_writer, out)
    exported = json.loads((out / "data/papers.json").read_text(encoding="utf-8"))
    assert [p["id"] for p in exported["robotic-surgery"]["papers"]] == ["color-iii-2026"]
    assert build_rows(out).errors == []


def test_a_failed_publish_leaves_nothing_behind(db_writer):
    publish_auto(db_writer, "k-1")
    before = manifest_of(db_writer)
    with pytest.raises(PublishError):
        publish_auto(db_writer, "k-2")  # same paper again: validate_data refuses the duplicate
    assert manifest_of(db_writer) == before
    assert count(db_writer, "select count(*) from app.publish_events where key = 'k-2'") == 0


def manifest_of(conn) -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        export_kb(conn, Path(tmp))
        return manifest(build_rows(Path(tmp)))["tables"]


def test_unpublishing_withdraws_the_paper_its_news_and_links(db_writer):
    publish_auto(db_writer, "k-1")
    linked = db_writer.execute("select id from app.papers where id <> 'test-auto-2026' limit 1").fetchone()[0]
    db_writer.execute(
        "insert into app.paper_relations (paper_id, target_id, type) values (%s, 'test-auto-2026', 'builds_on')",
        (linked,),
    )
    db_writer.execute(
        "insert into app.news (id, paper_id, published_at, headline, dek, key, figures, body, review_status)"
        " values ('test-story', 'test-auto-2026', '2026-11-15', '[\"h\"]', 'd', '{}', '[]', '[]', 'auto')"
    )
    with content_session("unpublish", "test-auto-2026", key="k-un", conn=db_writer) as session:
        session.record(unpublish("test-auto-2026", session.kb))
    assert count(db_writer, "select count(*) from app.public_papers where id = 'test-auto-2026'") == 0
    assert (
        count(db_writer, "select count(*) from app.papers where id = 'test-auto-2026' and withdrawn_at is not null")
        == 1
    )
    assert count(db_writer, "select count(*) from app.public_news where id = 'test-story'") == 0
    assert count(db_writer, "select count(*) from app.paper_relations where target_id = 'test-auto-2026'") == 0


def test_hand_curated_papers_cannot_be_unpublished(db_writer):
    curated = db_writer.execute("select id from app.papers where review_status is null limit 1").fetchone()[0]
    before = manifest_of(db_writer)
    with (
        pytest.raises(PublishError, match="人工整理"),
        content_session("unpublish", curated, key="k-curated", conn=db_writer) as session,
    ):
        session.record(unpublish(curated, session.kb))
    assert manifest_of(db_writer) == before


# --- two writers at once -------------------------------------------------------------------------------------------


@pytest.fixture
def committed_writer(tmp_path, monkeypatch):
    """Cutover committed for real; the content and writer mode are restored afterwards."""
    import psycopg

    with psycopg.connect(DB_URL) as connection:
        connection.execute("update app.content_writer set writer = 'json', watermark = null")
        apply(connection, build_rows(ROOT))
        connection.commit()
        content_writer.cutover(connection, copy_repo(tmp_path))
    monkeypatch.setenv("GUTHUB_CONTENT_DATABASE_URL", DB_URL)
    yield
    with psycopg.connect(DB_URL, autocommit=True) as connection:
        connection.execute("update app.content_writer set writer = 'json', watermark = null")
        connection.execute("delete from app.publish_events")
        connection.execute("delete from app.paper_watch_state")
        connection.execute("delete from app.papers where id like 'test-auto-%'")
        apply(connection, build_rows(ROOT))


def test_concurrent_writers_do_not_lose_each_others_papers(committed_writer):
    errors: list[BaseException] = []

    def write(n: int) -> None:
        try:
            paper = _paper(id=f"test-auto-{n}")
            paper |= {"doi": f"10.9999/concurrent-{n}", "pmid": f"9999000{n}"}
            paper["ai_suggested_filename"] = f"Test_Concurrent_{n}.html"
            with content_session("publish_paper", paper["doi"], key=f"k-concurrent-{n}") as session:
                entry = publish_paper(paper, "auto", TODAY, **session.kb_args)
                session.record(f"publish {entry['id']}")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(n,)) for n in (1, 2, 3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    import psycopg

    with psycopg.connect(DB_URL) as connection:
        ids = {r[0] for r in connection.execute("select id from app.public_papers where id like 'test-auto-%'")}
    assert ids == {"test-auto-1", "test-auto-2", "test-auto-3"}


def test_tracking_state_reads_and_writes_the_database_when_configured(committed_writer):
    import config

    tracked = config.load_tracked_dois()
    assert tracked == json.loads((ROOT / "data/tracked-dois.json").read_text())
    config.save_tracked_dois({**tracked, "10.9999/e3-tracking": {"topic": "mCRC-MSI-H", "added": TODAY}})
    assert "10.9999/e3-tracking" in config.load_tracked_dois()
    assert "10.9999/e3-tracking" not in json.loads((ROOT / "data/tracked-dois.json").read_text())  # repo untouched
    config.save_tracked_abstracts({"abs-1": {"added": TODAY}})
    assert config.load_tracked_abstracts() == {"abs-1": {"added": TODAY}}
