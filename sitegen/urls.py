"""Every URL the site emits is built here.

Links between pages are relative, so the site works under any base path or domain without a rebuild.
Absolute URLs (canonical, feeds, sitemap, JSON-LD) are the only ones that read ORIGIN and BASE.
"""

import posixpath

from .config import BASE, ORIGIN, Topic
from .models import NewsItem, Paper, Update


def absolute(path: str) -> str:
    return f"{ORIGIN}{BASE}{path}"


def relative(target: str, current: str, explicit_index: bool = False) -> str:
    """Link from the page at `current` to `target`; both are site-relative, a trailing slash is a directory.

    `explicit_index` spells out index.html for hosts that do not serve a directory's index page.
    """
    here = current if current.endswith("/") else posixpath.dirname(current) + "/"
    link = posixpath.relpath(target, here)
    if target.endswith("/"):
        link = "./" if link == "." else f"{link}/"
        if explicit_index:
            link += "index.html"
    return link


def paper_path(paper: Paper) -> str:
    return f"/papers/{paper.slug}/"


def news_path(item: NewsItem) -> str:
    return f"/news/{item.id}/"


def update_path(update: Update) -> str:
    return news_path(update.news) if update.news else paper_path(update.paper)


def topic_path(topic: Topic) -> str:
    return f"/mcrc/{topic.slug}/"


def feed_path(category: str) -> str:
    return f"/feed/{category}.xml"
