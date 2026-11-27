"""Layer 1a: Search PubMed for new papers matching topic queries."""

import argparse
import json
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

from config import (
    NCBI_API_KEY,
    PUBMED_FETCH_URL,
    PUBMED_RELDATE,
    PUBMED_SEARCH_URL,
    is_tracked,
    load_queries,
    load_tracked_dois,
    tracked_ids,
)
from config import (
    is_conference_season as _is_conference_season,
)
from net import fetch_with_retry

# NCBI E-utilities intermittently answers 400 to valid requests under load.
_NCBI_RETRY_STATUSES = (400, 429)


def esearch(query, reldate=PUBMED_RELDATE):
    """Search PubMed and return list of PMIDs."""
    params = {
        "db": "pubmed",
        "term": query,
        "reldate": reldate,
        "datetype": "edat",
        "retmax": 50,
        "retmode": "json",
        "usehistory": "n",
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    url = f"{PUBMED_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    data = json.loads(fetch_with_retry(url, timeout=30, retry_statuses=_NCBI_RETRY_STATUSES))
    return data.get("esearchresult", {}).get("idlist", [])


def efetch(pmids):
    """Fetch article metadata for a list of PMIDs. Returns list of dicts."""
    if not pmids:
        return []
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    url = f"{PUBMED_FETCH_URL}?{urllib.parse.urlencode(params)}"
    xml_data = fetch_with_retry(url, timeout=30, retry_statuses=_NCBI_RETRY_STATUSES)
    root = ET.fromstring(xml_data)
    articles = []
    for article in root.findall(".//PubmedArticle"):
        articles.append(_parse_article(article))
    return articles


def article_title(art) -> str:
    """The whole title. PubMed marks gene names up as <i>RAS</i>, and findtext stops at the first tag (#220)."""
    elem = art.find(".//ArticleTitle")
    return "".join(elem.itertext()) if elem is not None else ""


def _parse_article(article_elem):
    """Parse a PubmedArticle XML element into a dict."""
    medline = article_elem.find(".//MedlineCitation")
    art = medline.find(".//Article")

    pmid = medline.findtext(".//PMID", "")
    title = article_title(art)
    journal = art.findtext(".//Journal/ISOAbbreviation", "") or art.findtext(".//Journal/Title", "")
    year = art.findtext(".//Journal/JournalIssue/PubDate/Year", "")
    if not year:
        medline_date = art.findtext(".//Journal/JournalIssue/PubDate/MedlineDate", "")
        year = medline_date[:4] if medline_date else ""

    # Abstract
    abstract_parts = []
    for abs_text in art.findall(".//Abstract/AbstractText"):
        label = abs_text.get("Label", "")
        text = "".join(abs_text.itertext())
        if label:
            abstract_parts.append(f"{label}: {text}")
        else:
            abstract_parts.append(text)
    abstract = " ".join(abstract_parts)

    # Authors
    authors = []
    for author in art.findall(".//AuthorList/Author"):
        last = author.findtext("LastName", "")
        initials = author.findtext("Initials", "")
        if last:
            authors.append(f"{last} {initials}".strip())
    author_str = ", ".join(authors[:3])
    if len(authors) > 3:
        author_str += ", et al."

    # Publication types (Editorial, Letter, Randomized Controlled Trial, ...) and the
    # PMIDs this article comments on; used to route commentary away from full classification.
    publication_types = [pt.text or "" for pt in art.findall(".//PublicationTypeList/PublicationType")]
    comment_on_pmids = [
        cc.findtext("PMID", "")
        for cc in medline.findall(".//CommentsCorrectionsList/CommentsCorrections")
        if cc.get("RefType") == "CommentOn" and cc.findtext("PMID", "")
    ]

    # DOI
    doi = ""
    for id_elem in article_elem.findall(".//PubmedData/ArticleIdList/ArticleId"):
        if id_elem.get("IdType") == "doi":
            doi = id_elem.text or ""
            break

    return {
        "pmid": pmid,
        "doi": doi,
        "title": title,
        "authors": author_str,
        "journal": journal,
        "year": year,
        "abstract": abstract,
        "publication_types": publication_types,
        "comment_on_pmids": comment_on_pmids,
        "source": "pubmed",
    }


def resolve_dois(pmids: list[str]) -> dict[str, str]:
    """Map PMIDs to DOIs via efetch (PMIDs without a DOI are omitted)."""
    return {a["pmid"]: a["doi"] for a in efetch(pmids) if a.get("doi")}


# Conference abstract supplement queries — these catch meeting abstracts
# that get indexed in PubMed via JCO/Ann Oncol supplements
CONFERENCE_SUPPLEMENT_QUERIES = [
    # ASCO Annual Meeting abstracts (JCO supplement)
    '("J Clin Oncol"[jour]) AND ("Meeting Abstract"[pt]) AND (colorectal[ti] OR colon[ti] OR rectal[ti])',
    # ESMO abstracts (Ann Oncol supplement)
    '("Ann Oncol"[jour]) AND ("Meeting Abstract"[pt]) AND (colorectal[ti] OR colon[ti] OR rectal[ti])',
    # ASCRS/ESCP (Dis Colon Rectum)
    '("Dis Colon Rectum"[jour]) AND ("Meeting Abstract"[pt])',
]


def _select_topics(
    queries: dict,
    *,
    topic: str | None = None,
    include_shadow: bool = False,
    shadow_batch: int | None = None,
) -> list[str]:
    """Select active topic packs; shadow_only packs stay off unless explicitly requested."""
    if topic:
        return [topic]
    selected: list[str] = []
    for key, cfg in queries.items():
        if key in ("rss_feeds", "conference_seasons") or not isinstance(cfg, dict):
            continue
        if shadow_batch is not None:
            if cfg.get("rollout_batch") == shadow_batch:
                selected.append(key)
        elif include_shadow or not cfg.get("shadow_only", False):
            selected.append(key)
    return selected


def _merge_domain(existing: dict, domain: str | None) -> None:
    """Attach a cross-specialty domain onto an existing canonical candidate without duplicating the record."""
    if not domain:
        return
    primary = existing.get("primary_domain")
    secondaries = existing.setdefault("secondary_domains", [])
    if not primary:
        existing["primary_domain"] = domain
    elif domain != primary and domain not in secondaries:
        secondaries.append(domain)


def fetch_pubmed(
    topic=None,
    reldate=PUBMED_RELDATE,
    dry_run=False,
    *,
    include_shadow=False,
    shadow_batch=None,
):
    """Fetch new papers from PubMed. Returns list of canonical candidate dicts (cross-specialty merged)."""
    queries = load_queries()
    tracked_dois, tracked_pmids = tracked_ids(load_tracked_dois())

    topics = _select_topics(queries, topic=topic, include_shadow=include_shadow, shadow_batch=shadow_batch)
    candidates = []
    by_pmid: dict[str, dict] = {}

    for t in topics:
        if t not in queries:
            print(f"[WARN] Unknown topic: {t}", file=sys.stderr)
            continue
        cfg = queries[t]
        q = cfg["pubmed_query"]
        domain = cfg.get("domain")
        print(f"[PubMed] Searching topic={t}, reldate={reldate}d ...")
        pmids = esearch(q, reldate=reldate)
        print(f"  Found {len(pmids)} PMIDs")

        if not pmids:
            continue

        time.sleep(0.5)

        articles = efetch(pmids)
        for art in articles:
            if is_tracked(art, tracked_dois, tracked_pmids):
                continue
            pmid = art["pmid"]
            if pmid in by_pmid:
                _merge_domain(by_pmid[pmid], domain)
                continue
            art["topic"] = t
            art["primary_domain"] = domain
            art["secondary_domains"] = []
            by_pmid[pmid] = art
            candidates.append(art)

        print(f"  New candidates after dedup: {len([c for c in candidates if c['topic'] == t])}")
        time.sleep(0.5)

    # During conference season: also search for meeting abstract supplements
    in_season, conf_name = _is_conference_season()
    if in_season:
        print(f"\n[PubMed] Conference season ({conf_name}) — searching abstract supplements...")
        supplement_reldate = 30  # Wider window for meeting abstracts

        for supp_query in CONFERENCE_SUPPLEMENT_QUERIES:
            pmids = esearch(supp_query, reldate=supplement_reldate)
            if not pmids:
                continue
            time.sleep(0.5)

            articles = efetch(pmids)
            for art in articles:
                pmid = art["pmid"]
                if pmid in by_pmid:
                    continue
                if is_tracked(art, tracked_dois, tracked_pmids):
                    continue

                # Assign topic by keyword matching from title/abstract
                title_abs = (art.get("title", "") + " " + art.get("abstract", "")).lower()
                matched_topics = [
                    t
                    for t in topics
                    if t in queries and any(kw.lower() in title_abs for kw in queries[t].get("keywords", []))
                ]
                if matched_topics:
                    first = matched_topics[0]
                    art["topic"] = first
                    art["source"] = "pubmed_supplement"
                    art["primary_domain"] = queries[first].get("domain")
                    art["secondary_domains"] = []
                    for extra in matched_topics[1:]:
                        _merge_domain(art, queries[extra].get("domain"))
                    by_pmid[pmid] = art
                    candidates.append(art)

            time.sleep(0.5)

        supp_count = len([c for c in candidates if c.get("source") == "pubmed_supplement"])
        print(f"  Found {supp_count} new meeting abstract(s) from supplements")

    if dry_run:
        print(f"\n[DRY RUN] Total candidates: {len(candidates)}")
        for c in candidates:
            sec = f" (+{','.join(c['secondary_domains'])})" if c.get("secondary_domains") else ""
            print(f"  [{c['topic']}{sec}] {c['title'][:80]}...")
            print(f"    DOI: {c['doi']} | PMID: {c['pmid']}")

    return candidates


def main():
    parser = argparse.ArgumentParser(description="Fetch new papers from PubMed")
    parser.add_argument("--topic", help="Single topic to search (default: all active)")
    parser.add_argument("--reldate", type=int, default=PUBMED_RELDATE, help="Search window in days")
    parser.add_argument("--dry-run", action="store_true", help="Print results without saving")
    parser.add_argument("--include-shadow", action="store_true", help="Include shadow_only specialty packs")
    parser.add_argument("--shadow-batch", type=int, choices=[1, 2, 3], help="Run only a specific T4 shadow batch")
    args = parser.parse_args()

    candidates = fetch_pubmed(
        topic=args.topic,
        reldate=args.reldate,
        dry_run=args.dry_run,
        include_shadow=args.include_shadow,
        shadow_batch=args.shadow_batch,
    )

    if not args.dry_run:
        json.dump(candidates, sys.stdout, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
