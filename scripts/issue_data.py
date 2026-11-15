"""Machine-readable payloads embedded in bot-created GitHub issue bodies.

Issues stay human-readable markdown; the payload rides along in an HTML comment
so the accepted-issue → draft-PR workflow can rebuild the KB change without
re-parsing the prose. Checkboxes in the body record the reviewer's choices.
"""

import json
import re
from typing import Any

_MARKER = "paper-watch"


def embed(kind: str, payload: Any) -> str:
    """Return an HTML comment carrying ``payload`` as JSON.

    ``>`` is escaped inside the JSON so a ``-->`` in any string cannot end the
    comment early; ``>`` only occurs inside JSON strings, so this stays valid JSON.
    """
    data = json.dumps(payload, ensure_ascii=False).replace(">", "\\u003e")
    return f"<!-- {_MARKER}:{kind}\n{data}\n-->"


def extract(body: str, kind: str) -> Any | None:
    """Return the payload of the first ``kind`` block in ``body``, or None."""
    match = re.search(rf"<!-- {_MARKER}:{re.escape(kind)}\n(.*?)\n-->", body, re.DOTALL)
    return json.loads(match.group(1)) if match else None


def checkbox(index: int, checked: bool = False) -> str:
    """Task-list checkbox tagged with an index the parser can find again."""
    return f"- [{'x' if checked else ' '}] [c{index}]"


def checked_indices(body: str) -> set[int]:
    """Indices of the tagged checkboxes the reviewer ticked."""
    return {int(m.group(1)) for m in re.finditer(r"^- \[[xX]\] \[c(\d+)\]", body, re.MULTILINE)}
