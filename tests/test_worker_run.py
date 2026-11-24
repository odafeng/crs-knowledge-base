"""Tests for the Paper Watch worker entrypoint and direct PostgreSQL KB reads (K1 #251, K9 #259)."""

import importlib.util
from datetime import date
from pathlib import Path
from unittest.mock import patch

import config

_spec = importlib.util.spec_from_file_location("worker_run", Path(__file__).resolve().parent.parent / "worker/run.py")
assert _spec and _spec.loader
worker_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worker_run)


def test_scheduled_runs_full_scan_every_day():
    for day in range(16, 23):  # Mon through Sun (2026-11-16..22)
        assert worker_run.main_args(["--scheduled"], date(2026, 11, day)) == []
        assert worker_run.main_args(["--scheduled", "--dry-run"], date(2026, 11, day)) == ["--dry-run"]


def test_explicit_arguments_pass_through():
    assert worker_run.main_args(["--topic", "mCRC-MSI-H"], date(2026, 11, 18)) == ["--topic", "mCRC-MSI-H"]
    assert worker_run.main_args(["--daily"], date(2026, 11, 18)) == ["--daily"]


def test_worker_run_does_not_export_kb_to_disk():
    source = (Path(__file__).resolve().parent.parent / "worker/run.py").read_text(encoding="utf-8")
    assert "export_kb" not in source


def test_load_kb_data_from_conn_assembles_topic_papers_relations_and_commentary():
    topic_rows = [
        {
            "key": "mCRC-BRAF-V600E",
            "standard_of_care": [{"title": "1L", "reviewedAt": "2026-11-01"}],
            "soc_title": "現行治療方案",
            "metrics": {"mOS": {"max": 35, "bars": []}},
        }
    ]
    paper_rows = [
        {
            "id": "beacon-2019",
            "topic_key": "mCRC-BRAF-V600E",
            "year": 2019,
            "journal": "NEJM",
            "study_type": "Phase 3 RCT",
            "n": 665,
            "regimen": "EC vs SOC",
            "endpoint": "OS",
            "result": "mOS 9.0 vs 5.4 mo",
            "bottom_line": "2L standard",
            "doi": "10.1056/NEJMoa1908075",
            "source": "fulltext",
            "reviewed_at": date(2026, 6, 1),
            "added_at": date(2026, 6, 1),
            "source_file": "docs/beacon.html",
            "review_status": "accepted",
            "review_published_at": date(2026, 6, 1),
            "summary": None,
        }
    ]
    rel_rows = [{"paper_id": "beacon-2019", "target_id": "prior-1", "type": "builds_on"}]
    comm_rows = [
        {
            "paper_id": "beacon-2019",
            "doi": "10.1056/NEJMe1911223",
            "pmid": None,
            "title": "Editorial",
            "journal": "NEJM",
            "year": 2019,
            "type": "Editorial",
            "summary": "Key context",
            "critique": False,
            "new_data": False,
            "added_at": date(2026, 6, 2),
            "review_status": "auto",
            "review_published_at": date(2026, 6, 2),
        }
    ]
    responses = iter([topic_rows, paper_rows, rel_rows, comm_rows])

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, _sql):
            self._rows = next(responses)
            return self

        def fetchall(self):
            return self._rows

    class _Conn:
        def cursor(self, **_kw):
            return _Cur()

    data = config.load_kb_data_from_conn(_Conn())
    block = data["mCRC-BRAF-V600E"]
    assert block["standard_of_care"]["title"] == "現行治療方案"
    assert block["metrics"] == {"mOS": {"max": 35, "bars": []}}
    assert len(block["papers"]) == 1
    p = block["papers"][0]
    assert p["id"] == "beacon-2019"
    assert p["studyType"] == "Phase 3 RCT"
    assert p["relations"] == [{"targetId": "prior-1", "type": "builds_on"}]
    assert p["commentary"][0]["doi"] == "10.1056/NEJMe1911223"


def test_load_kb_data_uses_postgres_when_env_set(monkeypatch):
    monkeypatch.setenv(config.CONTENT_DATABASE_ENV, "postgresql://example/db")

    class _DummyConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    sentinel = {"mCRC-MSI-H": {"papers": [], "metrics": {}}}
    with (
        patch("psycopg.connect", return_value=_DummyConn()) as connect_mock,
        patch.object(config, "load_kb_data_from_conn", return_value=sentinel),
    ):
        assert config.load_kb_data() == sentinel
    connect_mock.assert_called_once_with("postgresql://example/db")
