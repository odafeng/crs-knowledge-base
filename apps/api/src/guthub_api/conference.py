"""Conference seasons (G9 #120, ADR-0008) for the API image, which holds only apps/api.

conference_seasons.json is a copy of conference_seasons in scripts/queries.json, the windows Paper Watch already uses
for its daily conference scans. refresh_conference_dates.py writes both, and tests/test_conference_seasons.py at the
repository root fails if they differ.
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

SEASONS_FILE = Path(__file__).with_name("conference_seasons.json")


def season_on(day: date, seasons: dict[str, Any] | None = None) -> str | None:
    """The name of the conference whose window (MM-DD, may wrap the new year) holds `day`, or None."""
    md = day.strftime("%m-%d")
    for season in (seasons if seasons is not None else json.loads(SEASONS_FILE.read_text())).values():
        start, end = season["start"], season["end"]
        if (start <= md <= end) if start <= end else (md >= start or md <= end):
            return season["name"]
    return None
