"""JSON-LD for the pages. Every page states who it is for: clinicians."""

from .config import LANG, SITE_NAME, TAGLINE
from .models import NewsItem, Paper
from .urls import absolute, news_path, paper_path

Crumbs = list[tuple[str, str]]  # (name, site-relative path)

_WEBSITE_ID = f"{absolute('/')}#website"


def _website() -> dict:
    return {
        "@type": "WebSite",
        "@id": _WEBSITE_ID,
        "name": SITE_NAME,
        "alternateName": TAGLINE,
        "url": absolute("/"),
        "inLanguage": LANG,
    }


def _breadcrumbs(crumbs: Crumbs) -> dict:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": absolute(path)}
            for i, (name, path) in enumerate(crumbs, start=1)
        ],
    }


def page_jsonld(name: str, description: str, path: str, crumbs: Crumbs, last_reviewed: str | None = None) -> dict:
    page = {
        "@type": "MedicalWebPage",
        "@id": absolute(path),
        "url": absolute(path),
        "name": name,
        "description": description,
        "inLanguage": LANG,
        "isPartOf": {"@id": _WEBSITE_ID},
        "audience": {"@type": "MedicalAudience", "audienceType": "Clinician"},
    }
    if last_reviewed:
        page["lastReviewed"] = last_reviewed
    return {"@context": "https://schema.org", "@graph": [_website(), page, _breadcrumbs(crumbs)]}


def paper_jsonld(paper: Paper, crumbs: Crumbs) -> dict:
    """A page for clinicians that summarises one published study; the study itself is `isBasedOn`."""
    data = page_jsonld(paper.title, paper.bottom_line, paper_path(paper), crumbs, paper.reviewed_at.isoformat())
    page = data["@graph"][1]
    page["about"] = {"@type": "Thing", "name": paper.topic.label}
    if paper.doi:
        page["isBasedOn"] = {
            "@type": "ScholarlyArticle",
            "identifier": {"@type": "PropertyValue", "propertyID": "DOI", "value": paper.doi},
            "sameAs": f"https://doi.org/{paper.doi}",
            "isPartOf": {"@type": "Periodical", "name": paper.journal},
            "datePublished": str(paper.year),
        }
    return data


def news_jsonld(item: NewsItem, crumbs: Crumbs) -> dict:
    """A news story is a NewsArticle about one entry; what it is written from is `isBasedOn`."""
    path = news_path(item)
    article = {
        "@type": "NewsArticle",
        "@id": absolute(path),
        "url": absolute(path),
        "headline": item.headline,
        "description": item.dek,
        "datePublished": item.published_at.isoformat(),
        "inLanguage": LANG,
        "isPartOf": {"@id": _WEBSITE_ID},
        "author": {"@type": "Organization", "name": SITE_NAME},
        "audience": {"@type": "MedicalAudience", "audienceType": "Clinician"},
        "about": {"@type": "Thing", "name": item.paper.topic.label},
        "mainEntityOfPage": absolute(path),
    }
    # The study by DOI when the entry has one; otherwise this site's page for the entry (a guideline, for example).
    article["isBasedOn"] = paper_jsonld(item.paper, crumbs)["@graph"][1].get("isBasedOn") or absolute(
        paper_path(item.paper)
    )
    return {"@context": "https://schema.org", "@graph": [_website(), article, _breadcrumbs(crumbs)]}
