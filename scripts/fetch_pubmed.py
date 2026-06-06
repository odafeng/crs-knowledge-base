"""Layer 1a: Search PubMed for new papers matching topic queries."""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

from config import (
    NCBI_API_KEY,
    PUBMED_FETCH_URL,
    PUBMED_RELDATE,
    PUBMED_SEARCH_URL,
    load_queries,
    load_tracked_dois,
)


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
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read())
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
    with urllib.request.urlopen(url, timeout=30) as resp:
        xml_data = resp.read()
    root = ET.fromstring(xml_data)
    articles = []
    for article in root.findall(".//PubmedArticle"):
        articles.append(_parse_article(article))
    return articles


def _parse_article(article_elem):
    """Parse a PubmedArticle XML element into a dict."""
    medline = article_elem.find(".//MedlineCitation")
    art = medline.find(".//Article")

    pmid = medline.findtext(".//PMID", "")
    title = art.findtext(".//ArticleTitle", "")
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
        "source": "pubmed",
    }


def fetch_pubmed(topic=None, reldate=PUBMED_RELDATE, dry_run=False):
    """Fetch new papers from PubMed. Returns list of candidate dicts."""
    queries = load_queries()
    tracked = load_tracked_dois()
    tracked_doi_set = set(tracked.keys())

    topics = [topic] if topic else [t for t in queries if t not in ("rss_feeds", "conference_seasons")]
    candidates = []

    for t in topics:
        if t not in queries:
            print(f"[WARN] Unknown topic: {t}", file=sys.stderr)
            continue
        q = queries[t]["pubmed_query"]
        print(f"[PubMed] Searching topic={t}, reldate={reldate}d ...")
        pmids = esearch(q, reldate=reldate)
        print(f"  Found {len(pmids)} PMIDs")

        if not pmids:
            continue

        # Rate limit: PubMed allows 3 req/s without API key, 10 with
        time.sleep(0.4)

        articles = efetch(pmids)
        for art in articles:
            if art["doi"] and art["doi"] in tracked_doi_set:
                continue
            art["topic"] = t
            candidates.append(art)

        print(f"  New candidates after dedup: {len([c for c in candidates if c['topic'] == t])}")
        time.sleep(0.4)

    if dry_run:
        print(f"\n[DRY RUN] Total candidates: {len(candidates)}")
        for c in candidates:
            print(f"  [{c['topic']}] {c['title'][:80]}...")
            print(f"    DOI: {c['doi']} | PMID: {c['pmid']}")

    return candidates


def main():
    parser = argparse.ArgumentParser(description="Fetch new papers from PubMed")
    parser.add_argument("--topic", help="Single topic to search (default: all)")
    parser.add_argument("--reldate", type=int, default=PUBMED_RELDATE, help="Search window in days")
    parser.add_argument("--dry-run", action="store_true", help="Print results without saving")
    args = parser.parse_args()

    candidates = fetch_pubmed(topic=args.topic, reldate=args.reldate, dry_run=args.dry_run)

    if not args.dry_run:
        json.dump(candidates, sys.stdout, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
