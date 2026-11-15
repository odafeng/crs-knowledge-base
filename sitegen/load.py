"""Read data/papers.json into the typed model."""

import json
import re
from datetime import date
from html import unescape
from pathlib import Path

from newsroom.gate import unsupported

from .config import ROBOTIC_KEY, ROBOTIC_PAGES, TOPICS
from .figures import Compare, CompareRow, Figure, Interval, Meter, Meters, Numbers, Stat
from .models import (
    Commentary,
    KnowledgeBase,
    NewsItem,
    NewsSection,
    Paper,
    RegulatoryRow,
    RoboticCard,
    RoboticSection,
    SocCard,
    TimelineItem,
)


def _clean_html(html: str) -> str:
    """Two repairs to the stored card bodies.

    An empty <th> is used as the corner cell, but a header cell must have a name.
    Drop links to source documents while retaining their text; their bodies are included in the new pages.
    """
    html = re.sub(r"<th>\s*</th>", "<td></td>", html)
    return re.sub(r'<a\b[^>]*href="docs/[^"]*"[^>]*>(.*?)</a>', r"\1", html, flags=re.S)


def _slug(paper_id: str) -> str:
    return paper_id.lower().replace("_", "-")


def _detail(root: Path, filename: str | None) -> str:
    if not filename or not (root / filename).is_file():
        return ""
    text = (root / filename).read_text(encoding="utf-8")
    body = re.search(r"<body[^>]*>(.*?)</body>", text, re.S | re.I)
    if not body:
        raise ValueError(f"Missing body in {filename}")
    text = re.sub(r"</?h1\b", lambda m: m[0].replace("h1", "h3"), body[1])
    text = re.sub(r"</?h2\b", lambda m: m[0].replace("h2", "h3"), text)
    text = re.sub(r'\sstyle="[^"]*"', "", text)
    return _clean_html(text)


def _commentary(raw: dict) -> Commentary:
    return Commentary(
        title=raw["title"],
        journal=raw["journal"],
        year=raw.get("year"),
        kind=raw.get("type", "Comment"),
        summary=raw["summary"],
        added_at=date.fromisoformat(raw["addedAt"]),
        doi=raw.get("doi"),
    )


def _stat(raw: dict) -> Stat:
    return Stat(raw["label"], raw["value"], raw.get("unit", ""))


def _figure(raw: dict) -> Figure:
    match raw["kind"]:
        case "numbers":
            return Numbers(tuple(_stat(s) for s in raw["stats"]))
        case "compare":
            rows = tuple(CompareRow(r["label"], r["unit"], r["a"], r["b"]) for r in raw["rows"])
            return Compare(raw["armA"], raw["armB"], rows)
        case "meters":
            return Meters(tuple(Meter(r["label"], r["percent"], r.get("detail", "")) for r in raw["rows"]))
        case "interval":
            return Interval(raw["label"], raw["point"], raw["low"], raw["high"], raw.get("note", ""))
    raise ValueError(f"unknown figure kind: {raw['kind']}")


def _news(path: Path, papers: dict[str, Paper]) -> tuple[NewsItem, ...]:
    items = [
        NewsItem(
            id=raw["id"],
            paper=papers[raw["paperId"]],
            published_at=date.fromisoformat(raw["publishedAt"]),
            headline_parts=tuple(raw["headline"]),
            dek=raw["dek"],
            key=_stat(raw["key"]),
            figures=tuple(_figure(f) for f in raw["figures"]),
            figure_note=raw.get("figureNote", ""),
            body=tuple(NewsSection(s["heading"], s["text"]) for s in raw["body"]),
            unreviewed=(raw.get("review") or {}).get("status") == "auto",
        )
        for raw in json.loads(path.read_text(encoding="utf-8"))
    ]
    return tuple(sorted(items, key=lambda n: n.published_at, reverse=True))  # stable: file order within a day


def load_kb(path: Path, news_path: Path | None = None) -> KnowledgeBase:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if news_path:
        sources = {p["id"]: p for block in raw.values() for p in block.get("papers", [])}
        for story in json.loads(news_path.read_text(encoding="utf-8")):
            if story["paperId"] not in sources:
                raise ValueError(f"Unknown source paper: {story['paperId']}")
            missing = unsupported(story, sources[story["paperId"]])
            if missing:
                raise ValueError(f"Unsupported numbers in {story['id']}: {', '.join(missing)}")
    papers, soc, regulatory = [], {}, []
    for topic in TOPICS:
        block = raw[topic.key]
        for p in block.get("papers", []):
            review = p.get("review") or {}
            reviewed_at = date.fromisoformat(p["reviewedAt"])
            papers.append(
                Paper(
                    id=p["id"],
                    slug=_slug(p["id"]),
                    topic=topic,
                    year=p["year"],
                    journal=unescape(p["journal"]),
                    study_type=p["studyType"],
                    n=p.get("n"),
                    regimen=unescape(p["regimen"]),
                    endpoint=unescape(p["endpoint"]),
                    result=unescape(p["result"]),
                    bottom_line=unescape(p["bottomLine"]),
                    doi=p.get("doi"),
                    source=p["source"],
                    reviewed_at=reviewed_at,
                    published_at=date.fromisoformat(review["publishedAt"][:10])
                    if review.get("publishedAt")
                    else reviewed_at,
                    unreviewed=review.get("status") == "auto",
                    commentary=tuple(_commentary(c) for c in p.get("commentary", [])),
                    detail_html=_detail(path.resolve().parent.parent, p.get("file")),
                )
            )
        cards = (block.get("standard_of_care") or {}).get("cards", [])
        soc[topic.slug] = tuple(
            SocCard(
                c["title"], _clean_html(c["body_html"]), date.fromisoformat(c["reviewedAt"]), tuple(c.get("refs", []))
            )
            for c in cards
        )
        for card in cards:
            for row in card.get("regulatory") or []:
                note = "；".join(n for n in (row.get("fdaNote"), row.get("tfdaNote"), row.get("nhiNote")) if n)
                regulatory.append(
                    RegulatoryRow(
                        topic,
                        row["regimen"],
                        row["fda"],
                        row["tfda"],
                        row["nhi"],
                        note,
                        date.fromisoformat(row["checkedAt"]),
                    )
                )
    robotic_raw = raw[ROBOTIC_KEY]
    robotic = tuple(
        RoboticSection(
            page,
            tuple(
                TimelineItem(t["yr"], t["venue"], t["finding"], t.get("file")) for t in robotic_raw[page.timeline_key]
            ),
            tuple(RoboticCard(c["title"], c["tag"], _clean_html(c["body"])) for c in robotic_raw[page.cards_key]),
            tuple(
                _detail(path.resolve().parent.parent, t["file"])
                for t in robotic_raw[page.timeline_key]
                if t.get("file", "").startswith("docs/")
            ),
        )
        for page in ROBOTIC_PAGES
    )
    news = _news(news_path, {p.id: p for p in papers}) if news_path else ()
    return KnowledgeBase(tuple(papers), soc, tuple(regulatory), robotic, news)
