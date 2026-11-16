"""Compare the Next.js site with the current site built by sitegen from the same data (C2d #93).

python tools/check_next_parity.py <sitegen output dir> <Next.js origin>

Run Next.js with GUTHUB_SITE_PUBLIC=1 so per-page noindex can be compared. Checks:
- every page of the current site exists on the Next.js site, with the same noindex decision;
- every internal link on every Next.js page resolves;
- each RSS/Atom/JSON feed has the same items per GUID (link, dates, title, summary, categories);
- sitemap.xml (as a set), robots.txt, canonical and JSON-LD per page (after the Seminar Hegemon -> GutHub rename).
Same-day item order may differ (the API orders by ID, sitegen by file order); IDs and content may not.
Exits 1 on any difference.
"""

import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

OLD, BASE = Path(sys.argv[1]), sys.argv[2].rstrip("/")
ATOM = "{http://www.w3.org/2005/Atom}"
SITEMAP = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
problems: list[str] = []


def fetch(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=30) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, ""


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("ok   " if ok else "DIFF ") + name + ("" if ok else f"\n     {detail}"))
    if not ok:
        problems.append(name)


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if value and name in ("href", "src") and tag in ("a", "link", "script", "img"):
                self.hrefs.append(value)


def jsonld(html: str) -> object:
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    return json.loads(match[1]) if match else None


def meta(html: str, pattern: str) -> str | None:
    match = re.search(pattern, html)
    return match[1] if match else None


CANONICAL = r'<link rel="canonical" href="([^"]+)"'
ROBOTS = r'<meta name="robots" content="([^"]+)"'

# 1. Pages, noindex, canonical and JSON-LD.
pages = sorted("/" + str(p.parent.relative_to(OLD)) + "/" for p in OLD.rglob("index.html") if p.parent != OLD)
pages = ["/", *pages]
missing, noindex_diff, canonical_diff, jsonld_diff, html = [], [], [], [], {}
for path in pages:
    status, body = fetch(path)
    if status != 200:
        missing.append(f"{path} -> {status}")
        continue
    html[path] = body
    old = (OLD / path.lstrip("/") / "index.html").read_text(encoding="utf-8")
    if ("noindex" in (meta(old, ROBOTS) or "")) != ("noindex" in (meta(body, ROBOTS) or "")):
        noindex_diff.append(path)
    if meta(old, CANONICAL) != meta(body, CANONICAL):
        canonical_diff.append(path)
    expected = json.loads(json.dumps(jsonld(old), ensure_ascii=False).replace("Seminar Hegemon", "GutHub"))
    if expected != jsonld(body):
        jsonld_diff.append(path)
check(f"{len(pages)} current pages exist on Next.js", not missing, ", ".join(missing[:10]))
check("noindex decisions match (GUTHUB_SITE_PUBLIC=1)", not noindex_diff, ", ".join(noindex_diff[:10]))
check("canonical links match", not canonical_diff, ", ".join(canonical_diff[:10]))
check("JSON-LD matches", not jsonld_diff, ", ".join(jsonld_diff[:10]))

# 2. Internal links on every Next.js page.
targets: dict[str, str] = {}
host = urlparse(BASE).netloc
for path, body in html.items():
    parser = Links()
    parser.feed(body)
    for href in parser.hrefs:
        url = urlparse(urljoin(BASE + path, href))
        if url.netloc == host and not url.path.startswith("/_next/"):
            targets.setdefault(url.path, path)
broken = [
    f"{source} -> {target} ({code})" for target, source in sorted(targets.items()) if (code := fetch(target)[0]) != 200
]
check(f"{len(targets)} internal link targets resolve", not broken, "; ".join(broken[:10]))


# 3. Feeds, compared per GUID.
def rss_items(text: str) -> dict:
    return {
        item.findtext("guid"): (
            item.findtext("link"),
            item.findtext("pubDate"),
            item.findtext("title"),
            item.findtext("description"),
            tuple(c.text for c in item.findall("category")),
        )
        for item in ET.fromstring(text).iter("item")
    }


for feed in ["/rss.xml", *("/feed/" + p.name for p in sorted((OLD / "feed").iterdir()))]:
    old_items, new_items = rss_items((OLD / feed.lstrip("/")).read_text(encoding="utf-8")), rss_items(fetch(feed)[1])
    changed = [guid for guid in old_items.keys() & new_items.keys() if old_items[guid] != new_items[guid]]
    check(
        f"{feed}: {len(new_items)} items",
        old_items.keys() == new_items.keys() and not changed,
        f"only current={sorted(old_items.keys() - new_items.keys())[:3]} only new={sorted(new_items.keys() - old_items.keys())[:3]} changed={changed[:3]}",
    )


def atom_entries(text: str) -> tuple:
    root = ET.fromstring(text)
    return root.findtext(ATOM + "id"), {
        entry.findtext(ATOM + "id"): (
            entry.find(ATOM + "link").get("href"),  # type: ignore[union-attr]
            entry.findtext(ATOM + "published"),
            entry.findtext(ATOM + "updated"),
            entry.findtext(ATOM + "title"),
            tuple(c.get("term") for c in entry.findall(ATOM + "category")),
        )
        for entry in root.findall(ATOM + "entry")
    }


check("/atom.xml", atom_entries((OLD / "atom.xml").read_text(encoding="utf-8")) == atom_entries(fetch("/atom.xml")[1]))


def json_items(feed: dict) -> dict:
    return {i["id"]: (i["url"], i["date_published"], i["title"], i["summary"], tuple(i["tags"])) for i in feed["items"]}


old_json, new_json = json.loads((OLD / "feed.json").read_text(encoding="utf-8")), json.loads(fetch("/feed.json")[1])
check("/feed.json", json_items(old_json) == json_items(new_json) and old_json["feed_url"] == new_json["feed_url"])


# 4. Sitemap (order is irrelevant to crawlers) and robots.txt.
def sitemap(text: str) -> set:
    return {(u.findtext(SITEMAP + "loc"), u.findtext(SITEMAP + "lastmod")) for u in ET.fromstring(text)}


old_map, new_map = sitemap((OLD / "sitemap.xml").read_text(encoding="utf-8")), sitemap(fetch("/sitemap.xml")[1])
check(
    f"/sitemap.xml: {len(new_map)} URLs",
    old_map == new_map,
    f"only current={sorted(old_map - new_map)[:3]} only new={sorted(new_map - old_map)[:3]}",
)
check("/robots.txt", (OLD / "robots.txt").read_text(encoding="utf-8") == fetch("/robots.txt")[1])

# 5. The search index (C3 #65): same entries, so search finds the same things. Order is not compared: the
# current site lists entries in data-file order, the Next.js site in the API's newest-first order.
old_index = sorted(json.loads((OLD / "search.json").read_text(encoding="utf-8")), key=lambda e: e["path"])
new_index = sorted(json.loads(fetch("/search.json")[1]), key=lambda e: e["path"])
check(f"/search.json: {len(new_index)} entries", old_index == new_index)

print(f"\nproblems: {len(problems)}")
sys.exit(1 if problems else 0)
