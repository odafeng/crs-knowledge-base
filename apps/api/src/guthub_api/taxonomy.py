"""API-local view of the versioned Central Topic Registry (T1 #282, ADR-0030).

Bundled as apps/api/src/guthub_api/taxonomy.json so `docker build apps/api` remains self-contained,
mirroring conference_seasons.json (ADR-0022). tests/test_taxonomy_registry.py enforces exact parity
with contracts/taxonomy.json.
"""

import json
from pathlib import Path
from typing import Any, Literal, get_args

type DomainSlug = Literal[
    "colorectal-oncology",
    "anorectal-diseases",
    "benign-colorectal-diseases",
    "pelvic-floor-functional",
    "minimally-invasive-surgery",
    "perioperative-care-nutrition",
    "endoscopy",
    "surgical-intelligence",
]
DOMAIN_ORDER: tuple[str, ...] = get_args(DomainSlug.__value__)

_REGISTRY_FILE = Path(__file__).with_name("taxonomy.json")
REGISTRY: dict[str, Any] = json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
TAXONOMY_VERSION: str = str(REGISTRY["version"])
