"""The Paper Watch job's daily schedule runs a full scan every day (K1 #251)."""

import importlib.util
from datetime import date
from pathlib import Path

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
