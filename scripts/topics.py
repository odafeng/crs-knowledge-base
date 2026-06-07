"""Single source of truth for topic keys and metadata.

Every module imports from here — no more magic strings scattered across files.
"""

from enum import Enum


class Topic(str, Enum):
    """All tracked topics. Values are the canonical string keys used everywhere."""

    BRAF = "mCRC-BRAF-V600E"
    KRAS_G12C = "mCRC-KRAS-G12C"
    MSI_H = "mCRC-MSI-H"
    HER2 = "mCRC-HER2"
    RAS_WT = "mCRC-RAS-wt"
    GENERIC = "generic-CRS"
    CONFERENCES = "conference-highlights"
    ROBOTIC = "robotic-surgery"


# GitHub label mapping
TOPIC_LABELS: dict[Topic, str] = {
    Topic.BRAF: "topic:braf-v600e",
    Topic.KRAS_G12C: "topic:kras-g12c",
    Topic.MSI_H: "topic:msi-h",
    Topic.HER2: "topic:her2",
    Topic.RAS_WT: "topic:ras-wt",
    Topic.GENERIC: "topic:generic-crs",
    Topic.CONFERENCES: "topic:conferences",
    Topic.ROBOTIC: "topic:robotic",
}

# Label colors for GitHub
LABEL_COLORS: dict[str, str] = {
    "new-paper": "0e8a16",
    "priority:high": "b60205",
    "parse-failed": "d93f0b",
    **{
        label: color
        for label, color in [
            ("topic:braf-v600e", "d93f0b"),
            ("topic:kras-g12c", "e99695"),
            ("topic:msi-h", "0075ca"),
            ("topic:her2", "7057ff"),
            ("topic:ras-wt", "fbca04"),
            ("topic:generic-crs", "c5def5"),
            ("topic:conferences", "e4e669"),
            ("topic:robotic", "006b75"),
        ]
    },
}

# JS array variable names in index.html (None = no array)
TOPIC_JS_VAR: dict[Topic, str | None] = {
    Topic.BRAF: "BRAF_PAPERS",
    Topic.KRAS_G12C: "G12C_PAPERS",
    Topic.MSI_H: "MSIH_PAPERS",
    Topic.HER2: "HER2_PAPERS",
    Topic.RAS_WT: "RASWT_PAPERS",
    Topic.GENERIC: "GENERIC_PAPERS",
    Topic.CONFERENCES: None,
    Topic.ROBOTIC: None,
}

# Docs directory per topic
TOPIC_DOCS_DIR: dict[Topic, str] = {t: t.value for t in Topic}

# Metrics variable names in index.html (None = no chart)
TOPIC_METRICS_VAR: dict[Topic, str | None] = {
    Topic.BRAF: "METRICS",
    Topic.KRAS_G12C: None,
    Topic.MSI_H: None,
    Topic.HER2: None,
    Topic.RAS_WT: None,
    Topic.GENERIC: None,
    Topic.CONFERENCES: None,
    Topic.ROBOTIC: "TME_METRICS",
}

# All topic string values (for validation)
ALL_TOPIC_KEYS: set[str] = {t.value for t in Topic}


def topic_from_str(key: str) -> Topic | None:
    """Convert a string key to Topic enum. Returns None if invalid."""
    try:
        return Topic(key)
    except ValueError:
        return None
