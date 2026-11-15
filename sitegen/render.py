"""Render every page with Jinja2 and write the site to disk."""

import hashlib
import json
import shutil
from collections.abc import Iterator
from datetime import date, timedelta
from functools import partial
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from . import config
from .feeds import Feed, to_atom, to_json_feed, to_rss
from .figures import fmt
from .icons import ICONS
from .models import KnowledgeBase, NewsItem, Paper, Update
from .schema import Crumbs, news_jsonld, page_jsonld, paper_jsonld
from .sitemap import robots_txt, sitemap_xml
from .urls import absolute, feed_path, news_path, paper_path, relative, topic_path

ROOT = Path(__file__).resolve().parent.parent
STYLES = ("fonts", "tokens", "base", "layout", "components", "content", "figures")
HOME: Crumbs = [("首頁", "/")]
NEWS: Crumbs = [*HOME, ("最新消息", "/news/")]
TOPICS: Crumbs = [*HOME, ("主題", "/topics/")]


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,  # a missing label or field fails the build instead of printing nothing
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals.update(
        site=config,
        absolute=absolute,
        paper_path=paper_path,
        news_path=news_path,
        topic_path=topic_path,
        feed_path=feed_path,
        topics=config.TOPICS,
        robotic_pages=config.ROBOTIC_PAGES,
        source_labels=config.SOURCE_LABELS,
        status_labels=config.STATUS_LABELS,
        status_style=config.STATUS_STYLE,
        commentary_labels=config.COMMENTARY_LABELS,
        icons=ICONS,
        fmt=fmt,
    )
    env.policies["json.dumps_kwargs"] = {"ensure_ascii": False}
    return env


def _write(out: Path, path: str, text: str) -> None:
    """path is site-relative; a trailing slash means <dir>/index.html."""
    target = out / path.lstrip("/")
    if path.endswith("/"):
        target = target / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _feeds(stream: list[Update]) -> Iterator[Feed]:
    yield Feed(f"{config.SITE_NAME}｜全部更新", config.DESCRIPTION, "/rss.xml", stream)
    news = [u for u in stream if u.kind == "news"]
    if news:
        yield Feed(f"{config.SITE_NAME}｜最新消息", "新文獻的新聞稿。", feed_path(config.NEWS_CATEGORY), news)
    for topic in config.TOPICS:
        mine = [u for u in stream if u.paper.topic == topic]
        if mine:  # an empty category gets no feed
            yield Feed(f"{config.SITE_NAME}｜{topic.label}", f"{topic.title}的最新收錄。", feed_path(topic.slug), mine)


def _search_index(kb: KnowledgeBase) -> list[dict]:
    """Paths are site-relative; search.js resolves them against the page it runs on."""
    stories = [
        {
            "path": news_path(n),
            "title": n.headline,
            "meta": f"最新消息 · {n.paper.topic.label}",
            "text": " ".join([n.headline, n.dek, *(s.text for s in n.body)]).lower(),
        }
        for n in kb.news
    ]
    papers = [
        {
            "path": paper_path(p),
            "title": p.title,
            "meta": f"{p.topic.label} · {p.study_type}",
            "text": " ".join(
                [
                    p.id,
                    p.regimen,
                    p.journal,
                    str(p.year),
                    p.topic.label,
                    p.study_type,
                    p.endpoint,
                    p.result,
                    p.bottom_line,
                ]
            ).lower(),
        }
        for p in kb.papers
    ]
    return stories + papers


def _manifest() -> str:
    """Web app manifest. A site added to the home screen is what lets iOS deliver push notifications."""
    return json.dumps(
        {
            "name": f"{config.SITE_NAME}｜{config.TAGLINE}",
            "short_name": config.SITE_NAME,
            "lang": config.LANG,
            "start_url": "./",
            "scope": "./",
            "display": "standalone",
            "background_color": "#F3F5FB",
            "theme_color": "#0E2270",
            "icons": [
                {"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
                {"src": "icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


class Site:
    """Renders pages into `out` and remembers which ones belong in the sitemap."""

    def __init__(self, kb: KnowledgeBase, out: Path, explicit_index: bool) -> None:
        self.kb, self.out, self.env, self.explicit_index = kb, out, _environment(), explicit_index
        self.updates = kb.updates()
        self.stream = sorted(kb.news_updates() + self.updates, key=lambda u: u.date, reverse=True)
        self.feeds = list(_feeds(self.stream))
        self.rendered = 0
        self.indexable: list[tuple[str, date | None]] = []
        latest = max(u.date for u in self.stream)
        since = latest - timedelta(days=6)
        self.common = {
            "feeds": {feed.path for feed in self.feeds},
            "last_updated": latest,
            "paper_count": len(kb.papers),
            "week_papers": sum(1 for u in self.updates if u.kind == "paper" and u.date >= since),
            "week_news": sum(1 for n in kb.news if n.published_at >= since),
            "index_suffix": "index.html" if explicit_index else "",
        }

    def page(
        self, template: str, path: str, *, indexable: bool = True, modified: date | None = None, **context
    ) -> None:
        url = partial(relative, current=path, explicit_index=self.explicit_index)
        html = self.env.get_template(template).render(
            path=path, url=url, noindex=not indexable, **self.common, **context
        )
        _write(self.out, path, html)
        self.rendered += 1
        if indexable:
            self.indexable.append((path, modified))

    def simple(self, template: str, path: str, title: str, description: str, parents: Crumbs = HOME, **context) -> None:
        """A page whose JSON-LD needs nothing beyond its name, description and breadcrumb."""
        crumbs = [*parents, (title, path)]
        self.page(template, path, crumbs=crumbs, jsonld=page_jsonld(title, description, path, crumbs), **context)


def build_site(kb: KnowledgeBase, out: Path, explicit_index: bool = False) -> dict[str, int]:
    if out.exists():
        if not (out / ".sitegen").is_file() and any(out.iterdir()):
            raise ValueError(f"Refusing to replace a non-generated output directory: {out}")
        shutil.rmtree(out)
    shutil.copytree(ROOT / "static", out)
    (out / ".sitegen").touch()
    _bundle_css(out)

    site = Site(kb, out, explicit_index)
    latest = site.common["last_updated"]
    site.page(
        "home.html.j2", "/", kb=kb, lead=kb.news[0] if kb.news else None, more=kb.news[1:4], updates=site.updates[:8],
        modified=latest, jsonld=page_jsonld(config.SITE_NAME, config.DESCRIPTION, "/", HOME),
    )  # fmt: skip
    site.simple(
        "news.html.j2", "/news/", "最新消息", "由 AI 依本站文獻條目撰寫的新聞稿。", news=kb.news, modified=latest
    )
    site.simple(
        "updates.html.j2", "/updates/", "文獻", "依收錄日排列的全部文獻與評論。", updates=site.updates, modified=latest
    )
    groups = [("mCRC 治療", "/mcrc/", "mcrc"), ("機器手臂手術", "/robotic/", "robotic")]
    site.simple("topics.html.j2", "/topics/", "主題", "依主題整理的試驗實證。", kb=kb, groups=groups)
    site.simple(
        "topics.html.j2",
        "/mcrc/",
        "mCRC 治療",
        "轉移性大腸直腸癌依分子分型整理的試驗實證。",
        TOPICS,
        kb=kb,
        groups=groups[:1],
    )
    site.simple(
        "topics.html.j2",
        "/robotic/",
        "機器手臂手術",
        "機器手臂 TME 與吻合的試驗實證。",
        TOPICS,
        kb=kb,
        groups=groups[1:],
    )
    site.simple(
        "subscribe.html.j2",
        "/subscribe/",
        "訂閱",
        "用推播或 RSS 接收新消息，或只訂閱關心的主題。",
        feed_list=site.feeds,
    )
    site.simple("about.html.j2", "/about/", "關於本站", "本站的定位、內容怎麼產生、AI 用在哪裡。")

    mcrc: Crumbs = [*TOPICS, ("mCRC 治療", "/mcrc/")]
    for topic in config.TOPICS:
        papers = kb.by_topic(topic)
        site.simple(
            "topic.html.j2", topic_path(topic), topic.label, f"{topic.title}的試驗實證，共 {len(papers)} 篇。", mcrc,
            topic=topic, papers=papers, soc=kb.soc[topic.slug], regulatory=[r for r in kb.regulatory if r.topic == topic],
            stories=[n for n in kb.news if n.paper.topic == topic][:3], modified=max((p.reviewed_at for p in papers), default=latest),
        )  # fmt: skip
    for section in kb.robotic:
        site.simple(
            "robotic.html.j2", f"/robotic/{section.page.slug}/", section.page.title, f"{section.page.title}的試驗實證。",
            [*TOPICS, ("機器手臂手術", "/robotic/")], section=section,
        )  # fmt: skip
    for paper in kb.papers:
        crumbs = [*mcrc, (paper.topic.label, topic_path(paper.topic)), (paper.regimen, paper_path(paper))]
        site.page(
            "paper.html.j2", paper_path(paper), paper=paper, crumbs=crumbs, related=_related(kb, paper),
            stories=[n for n in kb.news if n.paper == paper],
            indexable=not paper.unreviewed, modified=paper.reviewed_at, jsonld=paper_jsonld(paper, crumbs),
        )  # fmt: skip
    for item in kb.news:
        crumbs = [*NEWS, (item.headline, news_path(item))]
        site.page(
            "story.html.j2", news_path(item), item=item, crumbs=crumbs, others=_other_news(kb, item),
            indexable=not item.unreviewed, modified=item.published_at, jsonld=news_jsonld(item, crumbs),
        )  # fmt: skip

    _write_feeds(site)
    _write(out, "/search.json", json.dumps(_search_index(kb), ensure_ascii=False))
    _write(out, "/manifest.webmanifest", _manifest())
    _write(out, "/sitemap.xml", sitemap_xml(site.indexable))
    _write(out, "/robots.txt", robots_txt())
    _write_service_worker(out)
    return {
        "pages": site.rendered,
        "in_sitemap": len(site.indexable),
        "feeds": len(site.feeds) + 2,
    }


def _write_service_worker(out: Path) -> None:
    assets = sorted(p for p in out.rglob("*") if p.is_file() and p.name not in {"sw.js", ".sitegen"})
    digest = hashlib.sha256()
    urls = ["./"]
    for asset in assets:
        path = asset.relative_to(out).as_posix()
        digest.update(path.encode())
        digest.update(asset.read_bytes())
        urls.append(f"./{path}")
        if path.endswith("/index.html"):
            urls.append(f"./{path.removesuffix('index.html')}")
    worker = out / "sw.js"
    worker.write_text(
        f"const CACHE_NAME = 'seminar-hegemon-{digest.hexdigest()[:16]}';\n"
        f"const ASSETS = {json.dumps(urls, ensure_ascii=False)};\n" + worker.read_text(),
        encoding="utf-8",
    )


def _write_feeds(site: Site) -> None:
    everything = site.feeds[0]
    for feed in site.feeds:
        _write(site.out, feed.path, to_rss(feed))
    _write(site.out, "/atom.xml", to_atom(Feed(everything.title, everything.description, "/atom.xml", site.stream)))
    _write(
        site.out, "/feed.json", to_json_feed(Feed(everything.title, everything.description, "/feed.json", site.stream))
    )


def _bundle_css(out: Path) -> None:
    """Sources stay split by concern; the site ships one stylesheet, so a page makes one CSS request."""
    styles = out / "styles"
    parts = [styles / f"{name}.css" for name in STYLES]
    (styles / "site.css").write_text("\n".join(part.read_text(encoding="utf-8") for part in parts), encoding="utf-8")
    for part in parts:
        part.unlink()


def _related(kb: KnowledgeBase, paper: Paper) -> list[Paper]:
    return [p for p in kb.by_topic(paper.topic) if p.id != paper.id][:4]


def _other_news(kb: KnowledgeBase, item: NewsItem) -> list[NewsItem]:
    """Same topic first, then the newest of the rest."""
    rest = [n for n in kb.news if n.id != item.id]
    return sorted(rest, key=lambda n: n.paper.topic != item.paper.topic)[:3]
