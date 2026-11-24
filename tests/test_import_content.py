"""Content import from JSON into PostgreSQL (B4 #61).

Unit tests map the real knowledge base without a database. Integration tests need Supabase local with the
migrations applied (`supabase start`) and GUTHUB_TEST_DATABASE_URL; they skip without it unless GUTHUB_REQUIRE_DB=1.
Each integration test runs inside a transaction that is rolled back.
"""

import copy
import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import import_content
import pytest
from import_content import Rows, apply, build_rows, manifest

ROOT = Path(__file__).resolve().parent.parent
RAW = json.loads((ROOT / "data/papers.json").read_text(encoding="utf-8"))
NEWS = json.loads((ROOT / "data/news.json").read_text(encoding="utf-8"))
RAW_PAPERS = {p["id"]: (topic, p) for topic, block in RAW.items() for p in block.get("papers", [])}


@pytest.fixture(scope="module")
def rows() -> Rows:
    return build_rows(ROOT)


# --- mapping -------------------------------------------------------------------------------------------------------


def test_real_knowledge_base_maps_without_errors(rows):
    assert rows.errors == []
    counts = {name: len(items) for name, items in rows.tables.items()}
    assert counts["topics"] == len(RAW)
    assert counts["papers"] == len(RAW_PAPERS)
    assert counts["news"] == len(NEWS)
    assert counts["paper_relations"] == sum(len(p.get("relations", [])) for _, p in RAW_PAPERS.values())
    assert counts["research_commentary"] == sum(len(p.get("commentary", [])) for _, p in RAW_PAPERS.values())


def test_papers_keep_ids_sources_and_detail_documents(rows):
    for paper in rows.tables["papers"]:
        topic, raw = RAW_PAPERS[paper["id"]]
        assert paper["topic_key"] == topic
        assert paper["slug"] == raw["id"].lower().replace("_", "-")
        assert paper["n"] == raw.get("n")  # integer, string or null kept as-is
        assert paper["source_file"] == raw.get("file")
        assert bool(paper["detail_html"]) == bool(raw.get("file"))
        assert rows.sources.get(raw["file"]) if raw.get("file") else True


def test_topics_keep_treatment_cards_metrics_and_robotic_sections(rows):
    topics = {t["key"]: t for t in rows.tables["topics"]}
    for key, block in RAW.items():
        assert topics[key]["metrics"] == block.get("metrics", {})
        soc = block.get("standard_of_care") or {}
        expected_cards = [
            {**card, "body_html": import_content._clean_html(card["body_html"])} for card in soc.get("cards", [])
        ]
        assert topics[key]["standard_of_care"] == expected_cards
        assert topics[key]["soc_title"] == soc.get("title")
        for card in topics[key]["standard_of_care"]:
            assert card["body_html"] == import_content.sanitize_html(card["body_html"])
            assert "target=" not in card["body_html"]
            assert "style=" not in card["body_html"]
    robotic = topics["robotic-surgery"]["robotic_sections"]
    assert [s["slug"] for s in robotic] == ["tme", "anastomosis"]
    assert robotic[0]["timeline"] == [
        {**item, "finding": import_content.sanitize_html(item["finding"])} for item in RAW["robotic-surgery"]["tl_tme"]
    ]
    assert robotic[1]["cards"] == [
        {**card, "body": import_content._clean_html(card["body"])} for card in RAW["robotic-surgery"]["anast_cards"]
    ]
    assert any(robotic[0]["detailHtml"])


def test_write_layer_sanitizes_html_and_decodes_plain_text():
    assert import_content.plain_text("HR 0.65, p&lt;.001 &amp; OS") == "HR 0.65, p<.001 & OS"
    assert import_content.plain_text(42) == 42
    cleaned = import_content.sanitize_html(
        '<p style="color:red"><a href="https://example.com" target="_blank">Link</a><script>alert(1)</script></p>'
    )
    assert "<script" not in cleaned
    assert "style=" not in cleaned
    assert "target=" not in cleaned
    assert 'href="https://example.com"' in cleaned


def test_manifest_is_deterministic_and_tracks_sources(rows):
    first = manifest(rows)
    assert first == manifest(build_rows(ROOT))
    assert {"data/papers.json", "data/news.json"} <= first["sources"].keys()
    assert first["tables"]["papers"]["count"] == len(RAW_PAPERS)


def copy_repo(tmp_path: Path) -> Path:
    for name in ("data", "docs"):
        shutil.copytree(ROOT / name, tmp_path / name)
    return tmp_path


def test_missing_detail_document_is_reported(tmp_path):
    root = copy_repo(tmp_path)
    file = next(p["file"] for _, p in RAW_PAPERS.values() if p.get("file"))
    (root / file).unlink()
    assert any(file in error for error in build_rows(root).errors)


def test_unknown_topic_is_reported_not_dropped(tmp_path):
    root = copy_repo(tmp_path)
    raw = copy.deepcopy(RAW)
    raw["mCRC-NEW"] = {"papers": []}
    (root / "data/papers.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert "unknown topic in papers.json: mCRC-NEW" in build_rows(root).errors


def test_robotic_surgery_papers_are_imported(tmp_path):
    root = copy_repo(tmp_path)
    raw = copy.deepcopy(RAW)
    doc = root / "docs/robotic-surgery/COLOR_III_2026.html"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "<!doctype html><html><body><h2>COLOR III</h2><p>TaTME vs Lap TME</p></body></html>", encoding="utf-8"
    )
    raw["robotic-surgery"]["papers"].append(
        {
            "id": "color-iii-2026",
            "year": 2026,
            "journal": "Lancet",
            "studyType": "Phase 3 RCT",
            "n": 1100,
            "regimen": "TaTME vs Laparoscopic TME",
            "endpoint": "3-yr LRR",
            "result": "3-yr LRR 4.0% vs 4.5%",
            "bottomLine": "TaTME 非劣於腹腔鏡 TME",
            "doi": "10.1016/test-color-iii",
            "file": "docs/robotic-surgery/COLOR_III_2026.html",
            "relations": [],
            "source": "abstract",
            "reviewedAt": "2026-11-24",
            "review": {"status": "auto", "publishedAt": "2026-11-24"},
        }
    )
    (root / "data/papers.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    built = build_rows(root)
    assert built.errors == []
    robotic_papers = [p for p in built.tables["papers"] if p["topic_key"] == "robotic-surgery"]
    assert [p["id"] for p in robotic_papers] == ["color-iii-2026"]
    assert "<h3>COLOR III</h3>" in robotic_papers[0]["detail_html"]


def test_cli_dry_run_without_database_does_not_need_psycopg(capsys):
    assert import_content.main(["--dry-run"]) == 0
    assert '"papers"' in capsys.readouterr().out


def test_cli_requires_a_database_to_commit(monkeypatch):
    monkeypatch.delenv("GUTHUB_IMPORT_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        import_content.main([])


# --- database ------------------------------------------------------------------------------------------------------

DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB_URL and os.environ.get("GUTHUB_REQUIRE_DB") != "1", reason="no test database")


@pytest.fixture
def conn() -> Iterator:
    if not DB_URL:
        pytest.fail("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
    import psycopg

    with psycopg.connect(DB_URL) as connection, connection.transaction(force_rollback=True):
        # Start from empty content whatever the database holds; the rollback restores it afterwards.
        connection.execute(
            "truncate app.topics, app.papers, app.paper_relations, app.research_commentary, app.news, app.comments,"
            " app.comment_reports, app.moderation_events cascade"
        )
        yield connection


def export(conn) -> dict[str, list[dict]]:
    """Read imported content back in contract shape."""
    with conn.cursor() as cur:
        cur.execute("select paper_id, target_id, type from app.paper_relations")
        relations: dict[str, list] = {}
        for paper_id, target, kind in cur.fetchall():
            relations.setdefault(paper_id, []).append({"targetId": target, "type": kind})
        cur.execute(
            "select paper_id, doi, pmid, title, journal, year, type, summary, critique, new_data, added_at"
            " from app.research_commentary order by id"
        )
        commentary: dict[str, list] = {}
        for row in cur.fetchall():
            item = dict(
                zip(("doi", "pmid", "title", "journal", "year", "type", "summary", "critique"), row[1:9], strict=True)
            )
            commentary.setdefault(row[0], []).append({**item, "newData": row[9], "addedAt": row[10].isoformat()})
        cur.execute(
            "select id, slug, topic_key, year, journal, study_type, n, regimen, endpoint, result, bottom_line, doi,"
            " source, reviewed_at, detail_html, withdrawn_at is not null, added_at, review_status,"
            " review_published_at from app.papers"
        )
        papers = []
        for r in cur.fetchall():
            papers.append(
                {
                    "id": r[0], "slug": r[1], "topic": r[2], "year": r[3], "journal": r[4], "studyType": r[5],
                    "n": r[6], "regimen": r[7], "endpoint": r[8], "result": r[9], "bottomLine": r[10], "doi": r[11],
                    "source": r[12], "reviewedAt": r[13].isoformat(), "detailHtml": r[14], "withdrawn": r[15],
                    "relations": relations.get(r[0], []), "commentary": commentary.get(r[0], []),
                    **({"addedAt": r[16].isoformat()} if r[16] else {}),
                    **({"review": {"status": r[17], "publishedAt": r[18].isoformat()}} if r[17] else {}),
                }
            )  # fmt: skip
        cur.execute(
            "select id, paper_id, published_at, headline, dek, key, figures, figure_note, body, review_status,"
            " withdrawn_at is not null from app.news"
        )
        news = [
            {
                "id": r[0], "paperId": r[1], "publishedAt": r[2].isoformat(), "headline": r[3], "dek": r[4],
                "key": r[5], "figures": r[6], "figureNote": r[7], "body": r[8], "review": {"status": r[9]},
                "withdrawn": r[10],
            }
            for r in cur.fetchall()
        ]  # fmt: skip
    return {"papers": papers, "news": news}


@needs_db
def test_import_round_trips_every_paper_and_story(conn, rows):
    apply(conn, rows)
    exported = export(conn)
    by_id = {p["id"]: p for p in exported["papers"]}
    assert len(by_id) == len(RAW_PAPERS)
    for paper_id, (topic, raw) in RAW_PAPERS.items():
        db = by_id[paper_id]
        assert not db["withdrawn"]
        assert db["topic"] == topic
        for key, value in raw.items():
            if key == "file":
                continue
            got = db[key]
            if key == "relations":
                assert sorted(map(json.dumps, got)) == sorted(map(json.dumps, value)), paper_id
            elif key == "commentary":
                trimmed = [{k: v for k, v in c.items() if k in raw_c} for c, raw_c in zip(got, value, strict=True)]
                assert trimmed == value, paper_id
            else:
                assert got == value, (paper_id, key)
    stories = {n["id"]: n for n in exported["news"]}
    for raw in NEWS:
        db = stories[raw["id"]]
        for key in ("paperId", "publishedAt", "headline", "dek", "key", "figures", "body"):
            assert db[key] == raw[key], (raw["id"], key)
        assert db["figureNote"] == raw.get("figureNote")
        assert db["review"]["status"] == raw["review"]["status"]
    with conn.cursor() as cur:
        cur.execute("select key, standard_of_care, soc_title, metrics, robotic_sections from app.topics")
        topics = {row[0]: row[1:] for row in cur.fetchall()}
    assert topics.keys() == RAW.keys()
    for key, block in RAW.items():
        soc = block.get("standard_of_care") or {}
        expected_cards = [
            {**card, "body_html": import_content._clean_html(card["body_html"])} for card in soc.get("cards", [])
        ]
        assert topics[key][:3] == (expected_cards, soc.get("title"), block.get("metrics")), key
    robotic = {section["slug"]: section for section in topics["robotic-surgery"][3]}
    assert robotic["tme"]["timeline"] == [
        {**item, "finding": import_content.sanitize_html(item["finding"])} for item in RAW["robotic-surgery"]["tl_tme"]
    ]
    assert robotic["anastomosis"]["cards"] == [
        {**card, "body": import_content._clean_html(card["body"])} for card in RAW["robotic-surgery"]["anast_cards"]
    ]


@needs_db
def test_rerun_changes_nothing_and_adds_no_duplicates(conn, rows):
    first = apply(conn, rows)
    assert first["papers"]["inserted"] == len(RAW_PAPERS)
    before = export(conn)
    second = apply(conn, rows)
    for table in ("topics", "papers", "news"):
        assert second[table]["inserted"] == second[table]["updated"] == 0, table
        assert second[table].get("withdrawn", 0) == 0
    assert second["paper_relations"]["written"] == second["paper_relations"]["removed"]
    after = export(conn)
    key = lambda item: item["id"]  # noqa: E731
    assert sorted(after["papers"], key=key) == sorted(before["papers"], key=key)
    assert sorted(after["news"], key=key) == sorted(before["news"], key=key)


@needs_db
def test_removed_source_rows_are_withdrawn_then_restored(conn, rows):
    apply(conn, rows)
    smaller = copy.deepcopy(rows)
    gone = smaller.tables["news"].pop()["id"]
    paper = next(p for p in smaller.tables["papers"] if p["id"] not in {n["paper_id"] for n in rows.tables["news"]})
    smaller.tables["papers"].remove(paper)
    smaller.tables["paper_relations"] = [
        r for r in smaller.tables["paper_relations"] if paper["id"] not in (r["paper_id"], r["target_id"])
    ]
    smaller.tables["research_commentary"] = [
        c for c in smaller.tables["research_commentary"] if c["paper_id"] != paper["id"]
    ]
    changes = apply(conn, smaller)
    assert changes["papers"]["withdrawn"] == 1
    assert changes["news"]["withdrawn"] == 1
    with conn.cursor() as cur:
        cur.execute("select count(*) from app.public_papers where id = %s", (paper["id"],))
        assert cur.fetchone() == (0,)
        cur.execute("select count(*) from app.public_news where id = %s", (gone,))
        assert cur.fetchone() == (0,)

    restored = apply(conn, rows)
    assert restored["papers"]["updated"] == 1
    with conn.cursor() as cur:
        cur.execute("select withdrawn_at from app.papers where id = %s", (paper["id"],))
        assert cur.fetchone() == (None,)


@needs_db
def test_failure_rolls_back_the_whole_import(conn, rows):
    broken = copy.deepcopy(rows)
    broken.tables["paper_relations"].append(
        {"paper_id": broken.tables["papers"][0]["id"], "target_id": "does-not-exist", "type": "builds_on"}
    )
    with pytest.raises(RuntimeError, match="app.paper_relations"):
        apply(conn, broken)
    with conn.cursor() as cur:
        cur.execute("select count(*) from app.papers")
        assert cur.fetchone() == (0,)


@needs_db
def test_dry_run_reports_changes_but_writes_nothing(conn, rows):
    changes = apply(conn, rows, dry_run=True)
    assert changes["papers"]["inserted"] == len(RAW_PAPERS)
    with conn.cursor() as cur:
        cur.execute("select count(*) from app.papers")
        assert cur.fetchone() == (0,)


@needs_db
def test_sanitize_existing_scrubs_legacy_xss_and_entities(conn, rows):
    from psycopg.types.json import Jsonb

    apply(conn, rows)
    paper_id = rows.tables["papers"][0]["id"]
    with conn.cursor() as cur:
        cur.execute(
            "update app.papers set result = %s, detail_html = %s where id = %s",
            (
                "HR 0.65, p&lt;0.001 &amp; OS",
                '<p style="color:red"><img src=x onerror=alert(1)><a href="javascript:alert(1)">bad</a>'
                '<a href="https://example.com" target="_blank">ok</a></p>',
                paper_id,
            ),
        )
        cur.execute(
            "update app.topics set standard_of_care = %s where key = 'mCRC-BRAF-V600E'",
            (Jsonb([{"title": "t", "icon": "i", "body_html": "<img src=x onerror=alert(1)><p>safe</p>"}]),),
        )
    updated = import_content.sanitize_existing(conn)
    assert updated["papers"] == 1
    assert updated["topics"] == 1
    with conn.cursor() as cur:
        cur.execute("select result, detail_html from app.papers where id = %s", (paper_id,))
        result, detail_html = cur.fetchone()
        cur.execute("select standard_of_care from app.topics where key = 'mCRC-BRAF-V600E'")
        soc = cur.fetchone()[0]
    assert result == "HR 0.65, p<0.001 & OS"
    assert "<img" not in detail_html
    assert "onerror" not in detail_html
    assert "javascript:" not in detail_html
    assert "style=" not in detail_html
    assert "target=" not in detail_html
    assert 'href="https://example.com"' in detail_html
    assert soc[0]["body_html"] == "<p>safe</p>"
    # Idempotent on a second pass.
    assert import_content.sanitize_existing(conn) == {"papers": 0, "research_commentary": 0, "topics": 0}
