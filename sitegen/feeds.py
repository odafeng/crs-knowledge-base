"""RSS 2.0, Atom 1.0 and JSON Feed 1.1 from one list of updates."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import format_datetime
from xml.sax.saxutils import escape, quoteattr

from .config import FEED_LIMIT, FEED_TAG, LANG, SITE_NAME
from .models import Update
from .urls import absolute, update_path


@dataclass(frozen=True)
class Feed:
    title: str
    description: str
    path: str  # site-relative, e.g. /rss.xml
    updates: list[Update]

    @property
    def items(self) -> list[Update]:
        return self.updates[:FEED_LIMIT]


def _at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _guid(update: Update) -> str:
    """Stable across URL and domain changes, so a reader never sees an old item as new."""
    return f"{FEED_TAG}:{update.id}"


def _categories(update: Update) -> list[str]:
    paper = update.paper
    kind = {"news": "最新消息", "paper": paper.study_type, "commentary": "評論"}[update.kind]
    return [paper.topic.slug, paper.topic.label, kind]


def _modified(update: Update) -> date:
    """A paper entry counts as changed when it is re-reviewed; a news story or commentary does not change."""
    return max(update.date, update.paper.reviewed_at) if update.kind == "paper" else update.date


def _latest(feed: Feed) -> datetime:
    return _at(max(u.date for u in feed.items))


def to_rss(feed: Feed) -> str:
    items = "\n".join(
        f"""    <item>
      <title>{escape(u.title)}</title>
      <link>{absolute(update_path(u))}</link>
      <guid isPermaLink="false">{escape(_guid(u))}</guid>
      <pubDate>{format_datetime(_at(u.date), usegmt=True)}</pubDate>
      <description>{escape(u.summary)}</description>
{chr(10).join(f"      <category>{escape(c)}</category>" for c in _categories(u))}
    </item>"""
        for u in feed.items
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(feed.title)}</title>
    <link>{absolute("/")}</link>
    <description>{escape(feed.description)}</description>
    <language>zh-TW</language>
    <lastBuildDate>{format_datetime(_latest(feed), usegmt=True)}</lastBuildDate>
    <atom:link href={quoteattr(absolute(feed.path))} rel="self" type="application/rss+xml"/>
{items}
  </channel>
</rss>
"""


def to_atom(feed: Feed) -> str:
    entries = "\n".join(
        f"""  <entry>
    <title>{escape(u.title)}</title>
    <id>{escape(_guid(u))}</id>
    <link href={quoteattr(absolute(update_path(u)))} rel="alternate" type="text/html"/>
    <published>{_at(u.date).isoformat()}</published>
    <updated>{_at(_modified(u)).isoformat()}</updated>
    <summary>{escape(u.summary)}</summary>
{chr(10).join(f"    <category term={quoteattr(c)}/>" for c in _categories(u))}
  </entry>"""
        for u in feed.items
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="{LANG}">
  <title>{escape(feed.title)}</title>
  <subtitle>{escape(feed.description)}</subtitle>
  <id>{FEED_TAG}:feed{feed.path}</id>
  <link href={quoteattr(absolute("/"))} rel="alternate" type="text/html"/>
  <link href={quoteattr(absolute(feed.path))} rel="self" type="application/atom+xml"/>
  <updated>{_latest(feed).isoformat()}</updated>
  <author><name>{escape(SITE_NAME)}</name></author>
{entries}
</feed>
"""


def to_json_feed(feed: Feed) -> str:
    return json.dumps(
        {
            "version": "https://jsonfeed.org/version/1.1",
            "title": feed.title,
            "description": feed.description,
            "home_page_url": absolute("/"),
            "feed_url": absolute(feed.path),
            "language": LANG,
            "items": [
                {
                    "id": _guid(u),
                    "url": absolute(update_path(u)),
                    "title": u.title,
                    "summary": u.summary,
                    "content_text": u.summary,
                    "date_published": _at(u.date).isoformat(),
                    "tags": _categories(u),
                }
                for u in feed.items
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
