"""Typed view of data/papers.json. Loading turns loose dicts into these once; nothing else touches raw JSON."""

from dataclasses import dataclass, field
from datetime import date

from .config import RoboticPage, Topic
from .figures import Figure, Stat


@dataclass(frozen=True)
class Commentary:
    title: str
    journal: str
    year: int | None
    kind: str
    summary: str
    added_at: date
    doi: str | None


@dataclass(frozen=True)
class Paper:
    id: str
    slug: str
    topic: Topic
    year: int
    journal: str
    study_type: str
    n: int | str | None
    regimen: str
    endpoint: str
    result: str
    bottom_line: str
    doi: str | None
    source: str
    reviewed_at: date
    published_at: date
    unreviewed: bool  # published by the pipeline without a human look
    commentary: tuple[Commentary, ...] = ()
    detail_html: str = ""

    @property
    def title(self) -> str:
        return f"{self.regimen}（{self.journal} {self.year}）"


@dataclass(frozen=True)
class RegulatoryRow:
    topic: Topic
    regimen: str
    fda: str
    tfda: str
    nhi: str
    note: str
    checked_at: date


@dataclass(frozen=True)
class SocCard:
    title: str
    body_html: str
    reviewed_at: date
    refs: tuple[str, ...]


@dataclass(frozen=True)
class TimelineItem:
    year: str
    venue: str
    finding_html: str
    url: str | None


@dataclass(frozen=True)
class RoboticCard:
    title: str
    tag: str
    body_html: str


@dataclass(frozen=True)
class RoboticSection:
    page: RoboticPage
    timeline: tuple[TimelineItem, ...]
    cards: tuple[RoboticCard, ...]
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class NewsSection:
    heading: str
    text: str


@dataclass(frozen=True)
class NewsItem:
    """A news story about one paper. `key` is the single number shown on cards and in the push notification."""

    id: str
    paper: Paper
    published_at: date
    headline_parts: tuple[str, ...]  # phrases; a line may break between two of them, never inside one
    dek: str
    key: Stat
    figures: tuple[Figure, ...]
    figure_note: str
    body: tuple[NewsSection, ...]
    unreviewed: bool  # written by the pipeline without a human look

    @property
    def headline(self) -> str:
        return "".join(self.headline_parts)


@dataclass(frozen=True)
class Update:
    """One feed item: a news story, a paper, or a commentary attached to a paper."""

    id: str
    date: date
    paper: Paper
    title: str
    summary: str
    kind: str  # "news" | "paper" | "commentary"
    news: NewsItem | None = None


@dataclass(frozen=True)
class KnowledgeBase:
    papers: tuple[Paper, ...]
    soc: dict[str, tuple[SocCard, ...]] = field(default_factory=dict)  # by topic slug
    regulatory: tuple[RegulatoryRow, ...] = ()
    robotic: tuple[RoboticSection, ...] = ()
    news: tuple[NewsItem, ...] = ()  # newest first

    def by_topic(self, topic: Topic) -> list[Paper]:
        return sorted(
            (p for p in self.papers if p.topic == topic), key=lambda p: (p.year, p.published_at), reverse=True
        )

    def paper(self, paper_id: str) -> Paper | None:
        return next((p for p in self.papers if p.id == paper_id), None)

    def updates(self) -> list[Update]:
        rows = [
            Update(f"paper/{p.slug}", p.published_at, p, p.title, f"{p.result}。{p.bottom_line}", "paper")
            for p in self.papers
        ]
        rows += [
            Update(
                f"commentary/{p.slug}/{c.doi or c.title}",
                c.added_at,
                p,
                f"{c.journal} {c.year or ''}：{c.title}".strip(),
                c.summary,
                "commentary",
            )
            for p in self.papers
            for c in p.commentary
        ]
        return sorted(rows, key=lambda u: (u.date, u.paper.year), reverse=True)

    def news_updates(self) -> list[Update]:
        return [Update(f"news/{n.id}", n.published_at, n.paper, n.headline, n.dek, "news", n) for n in self.news]
