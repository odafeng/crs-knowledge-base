"""A news story may only state numbers that its source states.

The writer (an AI) gets one paper entry and returns a story. Before the story is published, every number
in it, in the headline, the text and the figures alike, must be found in the entry it was written from.
A story that fails is held for a person to look at; it is never published with the number removed.

    python -m newsroom.gate --kb data/papers.json --news data/news.json
"""

import argparse
import json
import re
from pathlib import Path

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_PAPER_FIELDS = ("regimen", "studyType", "n", "endpoint", "result", "bottomLine", "journal", "year")


def numbers(text: str) -> set[str]:
    """Every number in `text`, written one way: "4.0" and "4" are the same number."""
    return {f"{float(match):g}" for match in _NUMBER.findall(text)}


def _strings(value) -> list[str]:
    """All text and numbers anywhere inside a JSON value."""
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return [] if value is None or isinstance(value, bool) else [str(value)]


def story_numbers(story: dict) -> set[str]:
    stated = {key: story.get(key) for key in ("headline", "dek", "key", "figures", "figureNote", "body")}
    return numbers(" ".join(_strings(stated)))


def source_numbers(paper: dict) -> set[str]:
    return numbers(" ".join(str(paper[field]) for field in _PAPER_FIELDS if paper.get(field) is not None))


def unsupported(story: dict, paper: dict) -> list[str]:
    """Numbers the story states that the paper entry does not. Empty means the story passes."""
    return sorted(story_numbers(story) - source_numbers(paper), key=float)


def _papers(kb: dict) -> dict[str, dict]:
    return {paper["id"]: paper for block in kb.values() for paper in block.get("papers", [])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb", type=Path, required=True)
    parser.add_argument("--news", type=Path, required=True)
    args = parser.parse_args()
    papers = _papers(json.loads(args.kb.read_text(encoding="utf-8")))
    held = 0
    for story in json.loads(args.news.read_text(encoding="utf-8")):
        missing = unsupported(story, papers[story["paperId"]])
        held += bool(missing)
        print(
            f"{'HOLD' if missing else 'pass'}  {story['id']}"
            + (f"  not in the source: {', '.join(missing)}" if missing else "")
        )
    raise SystemExit(1 if held else 0)
