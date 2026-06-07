"""Tools available to each topic-specific AI agent.

Each agent can autonomously decide to:
1. Search PubMed for related/citing papers
2. Fetch full paper details by PMID
3. Look up existing papers in the knowledge base
4. Fetch a web page (DOI, conference abstract, etc.)
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from config import NCBI_API_KEY, PUBMED_FETCH_URL, PUBMED_SEARCH_URL, load_tracked_dois
from net import fetch_json, fetch_with_retry

# ---------------------------------------------------------------------------
# Tool definitions (JSON schema for Claude API)
# ---------------------------------------------------------------------------

AGENT_TOOLS = [
    {
        "name": "search_pubmed",
        "description": (
            "Search PubMed for papers matching a query. Use this to find related papers, "
            "check if a trial has follow-up publications, or find citing articles. "
            "Returns titles, PMIDs, DOIs, and abstracts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "PubMed search query. Supports MeSH terms, boolean operators, field tags like [AU], [TI], [PMID].",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5, max 10).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_paper_details",
        "description": (
            "Fetch full metadata and abstract for a paper by PMID. "
            "Use this when you need the complete abstract text to assess a paper's methodology and results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pmid": {
                    "type": "string",
                    "description": "PubMed ID (numeric string).",
                },
            },
            "required": ["pmid"],
        },
    },
    {
        "name": "lookup_existing_papers",
        "description": (
            "Look up what papers are already tracked in the CRS Knowledge Base. "
            "Use this to check if a paper or its predecessor is already in the KB, "
            "and to understand the relations between existing papers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic to look up. Options: mCRC-BRAF-V600E, mCRC-KRAS-G12C, mCRC-MSI-H, mCRC-HER2, mCRC-RAS-wt, robotic-surgery",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "web_fetch",
        "description": (
            "Fetch the text content of a web page. Use this to read a DOI landing page, "
            "conference abstract page, or journal article page for additional context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "query_guidelines",
        "description": (
            "Query the latest ASCO/ESMO/NCCN clinical guidelines from cached responses or PubMed. "
            "Use this to check what the current guideline recommendation is for a specific "
            "biomarker, treatment line, or clinical scenario. This helps you determine whether "
            "a new paper changes the standard of care. "
            "Example questions: "
            "'What is the ASCO guideline for first-line BRAF V600E mCRC treatment?', "
            "'Does NCCN recommend immunotherapy for MSI-H mCRC in the neoadjuvant setting?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "A clinical guideline question in English. Be specific about the biomarker, disease stage, and treatment line.",
                },
            },
            "required": ["question"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


_TOOL_DISPATCH = {
    "search_pubmed": lambda inp: _tool_search_pubmed(inp),
    "fetch_paper_details": lambda inp: _tool_fetch_paper_details(inp),
    "lookup_existing_papers": lambda inp: _tool_lookup_existing(inp),
    "web_fetch": lambda inp: _tool_web_fetch(inp),
    "query_guidelines": lambda inp: _tool_query_guidelines(inp),
}


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return the result string.

    Network errors and known exceptions → error JSON for the agent.
    Programming errors (KeyError, TypeError, etc.) → re-raised for debugging.
    """
    handler = _TOOL_DISPATCH.get(tool_name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    try:
        return handler(tool_input)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
        # Network errors — agent can decide to retry or use a different tool
        return json.dumps({"error": f"Network error in {tool_name}: {e}"})
    except (json.JSONDecodeError, ET.ParseError) as e:
        # Parse errors — data was fetched but malformed
        return json.dumps({"error": f"Parse error in {tool_name}: {e}"})


def _tool_search_pubmed(input_data):
    query = input_data["query"]
    max_results = min(input_data.get("max_results", 5), 10)

    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    url = f"{PUBMED_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    data = fetch_json(url)

    pmids = data.get("esearchresult", {}).get("idlist", [])
    if not pmids:
        return json.dumps({"results": [], "count": 0})

    time.sleep(0.5)  # PubMed rate limiting (3 req/s without key)

    fetch_params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    if NCBI_API_KEY:
        fetch_params["api_key"] = NCBI_API_KEY
    fetch_url = f"{PUBMED_FETCH_URL}?{urllib.parse.urlencode(fetch_params)}"
    xml_data = fetch_with_retry(fetch_url)

    root = ET.fromstring(xml_data)
    results = []
    for article in root.findall(".//PubmedArticle"):
        results.append(_parse_article_brief(article))

    return json.dumps({"results": results, "count": len(results)}, ensure_ascii=False)


def _tool_fetch_paper_details(input_data):
    pmid = input_data["pmid"]
    params = {"db": "pubmed", "id": pmid, "retmode": "xml"}
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    url = f"{PUBMED_FETCH_URL}?{urllib.parse.urlencode(params)}"
    xml_data = fetch_with_retry(url)

    root = ET.fromstring(xml_data)
    article = root.find(".//PubmedArticle")
    if not article:
        return json.dumps({"error": f"PMID {pmid} not found"})

    return json.dumps(_parse_article_full(article), ensure_ascii=False)


def _tool_lookup_existing(input_data):
    topic = input_data.get("topic", "")
    tracked = load_tracked_dois()

    # Filter by topic
    topic_papers = {
        doi: info for doi, info in tracked.items() if info.get("topic") == topic
    }

    # Also get the JS paper objects from topic_agents
    from topic_agents import _PAPERS_JS

    js_context = _PAPERS_JS.get(topic, "")

    return json.dumps(
        {
            "tracked_dois": topic_papers,
            "tracked_count": len(topic_papers),
            "existing_papers_js": js_context[:3000],  # Truncate if very long
        },
        ensure_ascii=False,
    )


def _tool_web_fetch(input_data):
    """Fetch and extract article text from a URL.

    Extraction priority: trafilatura (best) → readability-lxml → error.
    No regex HTML stripping — either the extractor works or we tell the agent.
    """
    url = input_data["url"]

    raw_html = None
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch {url}: {e}"})

    # 1. Try trafilatura (best quality, handles boilerplate removal)
    try:
        import trafilatura
        text = trafilatura.extract(raw_html, include_comments=False, include_tables=True)
        if text and len(text) > 50:
            title = trafilatura.extract_metadata(raw_html)
            title_str = title.title if title and title.title else ""
            return json.dumps({
                "title": title_str,
                "text": text[:4000],
                "extractor": "trafilatura",
            }, ensure_ascii=False)
    except ImportError:
        pass

    # 2. Fallback: readability-lxml
    try:
        from readability import Document
        doc = Document(raw_html)
        title = doc.title()
        content = doc.summary()
        text = re.sub(r"<[^>]+>", " ", content)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 50:
            return json.dumps({
                "title": title,
                "text": text[:4000],
                "extractor": "readability",
            }, ensure_ascii=False)
    except ImportError:
        pass

    # 3. Both extractors failed or returned empty — tell the agent honestly
    return json.dumps({
        "warning": "Could not extract meaningful content from this URL. "
                   "The page is likely JS-rendered (SPA) or behind authentication. "
                   "Use fetch_paper_details with PMID instead, or search_pubmed for the paper title.",
        "url": url,
        "raw_length": len(raw_html) if raw_html else 0,
    })


GUIDELINES_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "guidelines"


def _tool_query_guidelines(input_data):
    """Query clinical guidelines from pre-cached responses (originally sourced
    from OpenEvidence via unofficial cookie-based Playwright scraping) or
    fall back to PubMed guideline article search.

    Guidelines are cached as JSON files in data/guidelines/.
    Refresh with: python scripts/refresh_guidelines.py (requires OE relay).
    """
    question = input_data["question"].lower()

    if not GUIDELINES_CACHE_DIR.exists():
        return json.dumps({
            "error": "No guideline cache found.",
            "fallback": "Use your built-in domain knowledge and PubMed search to assess guideline relevance.",
            "hint": "Run: python scripts/refresh_guidelines.py to populate the cache.",
        })

    # Match question to cached topic files
    topic_keywords = {
        "mCRC-BRAF-V600E": ["braf", "v600e", "encorafenib", "cetuximab"],
        "mCRC-KRAS-G12C": ["kras", "g12c", "sotorasib", "adagrasib"],
        "mCRC-MSI-H": ["msi-h", "dmmr", "mismatch repair", "pembrolizumab", "immunotherapy"],
        "mCRC-HER2": ["her2", "erbb2", "trastuzumab", "tucatinib"],
        "mCRC-RAS-wt": ["ras wild", "anti-egfr", "cetuximab", "panitumumab", "sidedness"],
        "robotic-surgery": ["robotic", "robot", "tme", "cme", "laparoscop"],
    }

    matched_topics = []
    for topic, keywords in topic_keywords.items():
        if any(kw in question for kw in keywords):
            matched_topics.append(topic)

    if not matched_topics:
        matched_topics = list(topic_keywords.keys())

    # Try cached OE responses first
    results = []
    for topic in matched_topics:
        cache_file = GUIDELINES_CACHE_DIR / f"{topic}.json"
        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    cached = json.load(f)
                results.append({
                    "topic": topic,
                    "guideline_summary": cached.get("answer", "")[:2000],
                    "citations": cached.get("citations", [])[:5],
                    "cached_date": cached.get("date", "unknown"),
                    "source": "openevidence (cached)",
                })
            except (json.JSONDecodeError, OSError):
                continue

    if results:
        return json.dumps(results, ensure_ascii=False)

    # Fallback: search PubMed for guideline/consensus articles
    guideline_query = f"({question}) AND (guideline[PT] OR consensus[TI] OR recommendation[TI] OR NCCN[TI] OR ASCO[TI])"
    try:
        pubmed_result = _tool_search_pubmed({"query": guideline_query, "max_results": 3})
        parsed = json.loads(pubmed_result)
        if parsed.get("results"):
            return json.dumps({
                "source": "pubmed_guideline_search",
                "note": "No OpenEvidence cache available. Found these guideline articles from PubMed instead.",
                "results": parsed["results"],
            }, ensure_ascii=False)
    except Exception:
        pass

    return json.dumps({
        "error": f"No cached guidelines and PubMed fallback failed for: {', '.join(matched_topics)}",
        "fallback": "Use your built-in domain knowledge to assess guideline relevance.",
    })


# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------


def _parse_article_brief(article_elem):
    medline = article_elem.find(".//MedlineCitation")
    art = medline.find(".//Article")
    pmid = medline.findtext(".//PMID", "")
    title = art.findtext(".//ArticleTitle", "")
    journal = art.findtext(".//Journal/ISOAbbreviation", "")
    year = art.findtext(".//Journal/JournalIssue/PubDate/Year", "")

    doi = ""
    for id_elem in article_elem.findall(".//PubmedData/ArticleIdList/ArticleId"):
        if id_elem.get("IdType") == "doi":
            doi = id_elem.text or ""
            break

    # Brief abstract (first 300 chars)
    abstract_parts = []
    for abs_text in art.findall(".//Abstract/AbstractText"):
        abstract_parts.append("".join(abs_text.itertext()))
    abstract = " ".join(abstract_parts)[:300]

    return {
        "pmid": pmid,
        "doi": doi,
        "title": title,
        "journal": journal,
        "year": year,
        "abstract_preview": abstract,
    }


def _parse_article_full(article_elem):
    medline = article_elem.find(".//MedlineCitation")
    art = medline.find(".//Article")
    pmid = medline.findtext(".//PMID", "")
    title = art.findtext(".//ArticleTitle", "")
    journal = art.findtext(".//Journal/ISOAbbreviation", "")
    year = art.findtext(".//Journal/JournalIssue/PubDate/Year", "")

    # Full abstract
    abstract_parts = []
    for abs_text in art.findall(".//Abstract/AbstractText"):
        label = abs_text.get("Label", "")
        text = "".join(abs_text.itertext())
        if label:
            abstract_parts.append(f"{label}: {text}")
        else:
            abstract_parts.append(text)
    abstract = "\n".join(abstract_parts)

    # Authors
    authors = []
    for author in art.findall(".//AuthorList/Author"):
        last = author.findtext("LastName", "")
        initials = author.findtext("Initials", "")
        if last:
            authors.append(f"{last} {initials}".strip())

    # DOI
    doi = ""
    for id_elem in article_elem.findall(".//PubmedData/ArticleIdList/ArticleId"):
        if id_elem.get("IdType") == "doi":
            doi = id_elem.text or ""
            break

    # MeSH terms
    mesh_terms = []
    for mesh in medline.findall(".//MeshHeadingList/MeshHeading/DescriptorName"):
        mesh_terms.append(mesh.text or "")

    return {
        "pmid": pmid,
        "doi": doi,
        "title": title,
        "authors": ", ".join(authors),
        "journal": journal,
        "year": year,
        "abstract": abstract,
        "mesh_terms": mesh_terms[:10],
    }
