"""Layer 1a: Search PubMed for new papers matching topic queries."""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from config import (
    NCBI_API_KEY,
    PUBMED_FETCH_URL,
    PUBMED_RELDATE,
    PUBMED_SEARCH_URL,
    load_queries,
    load_tracked_dois,
)
from config import (
    is_conference_season as _is_conference_season,
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


def fetch_pubmed(topic=None, reldate=PUBMED_RELDATE, dry_run=False):
    """Fetch new papers from PubMed. Returns list of candidate dicts."""
    queries = load_queries()
    tracked = load_tracked_dois()
    tracked_doi_set = set(tracked.keys())

    topics = [topic] if topic else [t for t in queries if t not in ("rss_feeds", "conference_seasons")]
    candidates = []
    seen_pmids = set()

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

        time.sleep(0.5)

        articles = efetch(pmids)
        for art in articles:
            if art["doi"] and art["doi"] in tracked_doi_set:
                continue
            if art["pmid"] in seen_pmids:
                continue
            seen_pmids.add(art["pmid"])
            art["topic"] = t
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
                if art["pmid"] in seen_pmids:
                    continue
                if art["doi"] and art["doi"] in tracked_doi_set:
                    continue
                seen_pmids.add(art["pmid"])

                # Assign topic by keyword matching from title/abstract
                title_abs = (art.get("title", "") + " " + art.get("abstract", "")).lower()
                for t in topics:
                    if t not in queries:
                        continue
                    keywords = queries[t].get("keywords", [])
                    if any(kw.lower() in title_abs for kw in keywords):
                        art["topic"] = t
                        art["source"] = "pubmed_supplement"
                        candidates.append(art)
                        break

            time.sleep(0.5)

        supp_count = len([c for c in candidates if c.get("source") == "pubmed_supplement"])
        print(f"  Found {supp_count} new meeting abstract(s) from supplements")

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
