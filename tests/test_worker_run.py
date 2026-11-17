"""The Paper Watch job's daily schedule picks the same scan the GitHub workflow's two crons did (E3 #76)."""

import importlib.util
from datetime import date
from pathlib import Path

_spec = importlib.util.spec_from_file_location("worker_run", Path(__file__).resolve().parent.parent / "worker/run.py")
assert _spec and _spec.loader
worker_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worker_run)


def test_tuesday_and_friday_run_the_full_scan():
    assert worker_run.main_args(["--scheduled"], date(2026, 11, 17)) == []  # Tuesday
    assert worker_run.main_args(["--scheduled", "--dry-run"], date(2026, 11, 20)) == ["--dry-run"]  # Friday


def test_other_days_scan_only_in_conference_season():
    assert worker_run.main_args(["--scheduled"], date(2026, 11, 18)) == ["--daily"]  # Wednesday
    assert worker_run.main_args(["--scheduled", "--dry-run"], date(2026, 11, 22)) == ["--daily", "--dry-run"]  # Sunday


def test_explicit_arguments_pass_through():
    assert worker_run.main_args(["--topic", "mCRC-MSI-H"], date(2026, 11, 18)) == ["--topic", "mCRC-MSI-H"]
