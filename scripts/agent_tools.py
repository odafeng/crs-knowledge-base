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
            "Query the latest ASCO/ESMO/NCCN clinical guidelines via OpenEvidence. "
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


def execute_tool(tool_name, tool_input):
    """Execute a tool and return the result string."""
    try:
        if tool_name == "search_pubmed":
            return _tool_search_pubmed(tool_input)
        elif tool_name == "fetch_paper_details":
            return _tool_fetch_paper_details(tool_input)
        elif tool_name == "lookup_existing_papers":
            return _tool_lookup_existing(tool_input)
        elif tool_name == "web_fetch":
            return _tool_web_fetch(tool_input)
        elif tool_name == "query_guidelines":
            return _tool_query_guidelines(tool_input)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


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
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read())

    pmids = data.get("esearchresult", {}).get("idlist", [])
    if not pmids:
        return json.dumps({"results": [], "count": 0})

    time.sleep(0.3)

    # Fetch details
    fetch_params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    if NCBI_API_KEY:
        fetch_params["api_key"] = NCBI_API_KEY
    fetch_url = f"{PUBMED_FETCH_URL}?{urllib.parse.urlencode(fetch_params)}"

    with urllib.request.urlopen(fetch_url, timeout=15) as resp:
        xml_data = resp.read()

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
    with urllib.request.urlopen(url, timeout=15) as resp:
        xml_data = resp.read()

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
    url = input_data["url"]

    # Try readability extraction first (better quality)
    try:
        from readability import Document
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")

        doc = Document(raw_html)
        title = doc.title()
        content = doc.summary()

        # Strip remaining HTML tags from readability output
        text = re.sub(r"<[^>]+>", " ", content)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) < 50:
            return json.dumps({
                "warning": "Page content is very short — may be JS-rendered. Try fetch_paper_details with PMID instead.",
                "title": title,
                "text": text[:500],
            })

        return json.dumps({
            "title": title,
            "text": text[:4000],
        }, ensure_ascii=False)

    except ImportError:
        pass  # readability not installed, fall back to regex
    except Exception:
        pass

    # Fallback: regex-based extraction
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,text/plain",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="replace")

        text = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL)
        text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL)
        text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) < 50:
            return json.dumps({
                "warning": "Page content is very short — likely JS-rendered. Use fetch_paper_details with PMID instead.",
                "text": text[:500],
            })

        return text[:4000]
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch {url}: {e}"})


GUIDELINES_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "guidelines"


def _tool_query_guidelines(input_data):
    """Query clinical guidelines from pre-cached OpenEvidence responses.

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
