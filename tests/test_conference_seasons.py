"""The API reads its own copy of the conference windows (G9 #120); it must match the one Paper Watch uses."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_api_copy_of_conference_seasons_matches_queries_json() -> None:
    queries = json.loads((ROOT / "scripts/queries.json").read_text())
    copy = json.loads((ROOT / "apps/api/src/guthub_api/conference_seasons.json").read_text())
    assert copy == queries["conference_seasons"], "run scripts/refresh_conference_dates.py or copy the windows over"
