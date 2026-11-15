"""Site constants and the topic registry: the one place to rename, re-order or add a topic."""

import os
from dataclasses import dataclass

SITE_NAME = "Seminar Hegemon"
TAGLINE = "大腸直腸外科實證更新"
DESCRIPTION = "給大腸直腸外科醫師的實證更新：追蹤 mCRC 治療與機器手臂手術的新試驗、指引與給付異動。"
ORIGIN = "https://odafeng.github.io"
BASE = "/crs-knowledge-base"
LANG = "zh-Hant-TW"
FEED_TAG = "tag:odafeng.github.io,2026"  # stable prefix for <guid> and Atom <id>; never change it
FEED_LIMIT = 30


@dataclass(frozen=True)
class Topic:
    key: str  # key in data/papers.json
    slug: str  # URL segment, and the {{category}} of /feed/{{category}}.xml
    label: str  # short name for tags and navigation
    title: str  # page heading


TOPICS = (
    Topic("mCRC-BRAF-V600E", "braf-v600e", "BRAF V600E", "BRAF V600E 突變型 mCRC"),
    Topic("mCRC-KRAS-G12C", "kras-g12c", "KRAS G12C", "KRAS G12C 突變型 mCRC"),
    Topic("mCRC-MSI-H", "msi-h", "MSI-H / dMMR", "MSI-H / dMMR 大腸直腸癌"),
    Topic("mCRC-HER2", "her2", "HER2", "HER2 陽性 mCRC"),
    Topic("mCRC-RAS-wt", "ras-wt", "RAS wild-type", "RAS 野生型 mCRC"),
    Topic("generic-CRS", "later-line", "後線治療", "mCRC 後線治療與跨分子型"),
)


@dataclass(frozen=True)
class RoboticPage:
    slug: str
    title: str
    timeline_key: str
    cards_key: str


ROBOTIC_KEY = "robotic-surgery"
ROBOTIC_PAGES = (
    RoboticPage("tme", "機器手臂 TME", "tl_tme", "tme_cards"),
    RoboticPage("anastomosis", "機器手臂吻合", "tl_anast", "anast_cards"),
)

SOURCE_LABELS = {"curated": "人工整理", "fulltext": "全文", "abstract": "摘要", "secondary": "次級來源"}
# Same vocabulary as scripts/validate.py: one label set per regulator.
STATUS_LABELS = {
    "fda": {"approved": "已核准", "accelerated": "加速核准", "none": "未核准", "unknown": "未確認"},
    "tfda": {"approved": "已核准", "none": "未核准", "unknown": "未確認"},
    "nhi": {"covered": "已給付", "conditional": "有條件給付", "none": "未給付", "unknown": "未確認"},
}
# How each regulatory state is drawn: (style, icon). The label always accompanies it.
STATUS_STYLE = {
    "approved": ("good", "check"),
    "covered": ("good", "check"),
    "accelerated": ("partial", "clock"),
    "conditional": ("partial", "clock"),
    "none": ("none", "x"),
    "unknown": ("unknown", "question"),
}
NEWS_CATEGORY = "news"  # /feed/news.xml; never a topic slug

# Web Push, set by the build environment (repository variables in CI). None of the three is a secret.
# Without the first two the bell stays hidden: the site works without a push backend.
PUSH_PUBLIC_KEY = os.environ.get("PUSH_PUBLIC_KEY", "")  # VAPID public key, base64url
PUSH_API = os.environ.get("PUSH_API", "")  # where subscriptions are stored, e.g. https://<project>.supabase.co/rest/v1
PUSH_API_KEY = os.environ.get("PUSH_API_KEY", "")  # the store's publishable key, if it wants one
# A preview build shows the bell and its states without registering anything (hosts that forbid service workers).
PUSH_PREVIEW = os.environ.get("PUSH_PREVIEW", "") == "1"

COMMENTARY_LABELS = {"Editorial": "社論", "Comment": "評論", "Letter": "讀者投書", "News": "新聞"}
