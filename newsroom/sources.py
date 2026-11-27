"""Direct Newsroom Source Registry, SSRF-hardened HTTP collector, and deterministic deduplicator (N2 #287, ADR-0031).

Initial 6 direct sources (locked in ADR-0031):
1. tw-nhi-tfda         — Taiwan NHI & TFDA (reuses scripts/regulatory_watch.py findings + announcement feeds)
2. fda-oncology        — FDA Oncology Approvals (strictly filtered to colorectal / anal cancer)
3. ascrs-escp          — ASCRS / ESCP clinical guidelines & society updates
4. clinicaltrials-gov  — ClinicalTrials.gov API v2 (distinguishes substantive milestones from routine edits)
5. tw-crs-society      — Taiwan Society of Colon and Rectal Surgeons (crs.org.tw)
6. eras-esge           — ERAS Society & ESGE (perioperative care, nutrition, and endoscopy)
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from typing import Any

MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MiB hard response cap
MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = 15.0
_TRACKING_PARAMS = frozenset({"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"})
_CRC_RE = re.compile(
    r"\b(colorectal|colon cancer|rectal cancer|anal cancer|mcrc|crc|dmmr|msi-h|braf v600e|kras g12c)\b"
    r"|大腸直腸|結直腸|直腸癌|結腸癌|肛門癌",
    re.IGNORECASE,
)
_PERIO_RE = re.compile(r"\b(eras|enhanced recovery|prehabilitation|nutrition|anastomotic|stoma)\b", re.IGNORECASE)
_ENDO_RE = re.compile(r"\b(colonoscopy|esd|emr|eftr|polypectomy|endoscop)\b", re.IGNORECASE)
_NCT_RE = re.compile(r"\b(NCT\d{8})\b", re.IGNORECASE)
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s<>\"']+)", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


class SSRFFetchError(ValueError):
    """Raised when a URL or any redirect target violates HTTPS or private-network SSRF rules."""


class ResponseTooLargeError(ValueError):
    """Raised when an upstream HTTP response exceeds max_bytes."""


@dataclass(frozen=True)
class SourceDefinition:
    id: str
    name: str
    source_type: str  # regulatory | society | trial_registry | guideline | journal | intake_repo
    base_url: str
    terms_reviewed_at: str  # YYYY-MM-DD
    poll_interval_minutes: int
    trust_tier: str  # tier1 | tier2 | tier3
    enabled: bool = False
    default_domains: tuple[str, ...] = ()
    geography: str = "global"


INITIAL_SOURCES: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        id="tw-nhi-tfda",
        name="台灣健保署與食藥署（NHI / TFDA）",
        source_type="regulatory",
        base_url="https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId=A21030000I-E41001-001",
        terms_reviewed_at="2026-11-27",
        poll_interval_minutes=720,
        trust_tier="tier1",
        enabled=False,
        default_domains=("colorectal-oncology",),
        geography="taiwan",
    ),
    SourceDefinition(
        id="fda-oncology",
        name="US FDA Oncology Approvals",
        source_type="regulatory",
        base_url="https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/drugs/rss.xml",
        terms_reviewed_at="2026-11-27",
        poll_interval_minutes=360,
        trust_tier="tier1",
        enabled=False,
        default_domains=("colorectal-oncology",),
        geography="us",
    ),
    SourceDefinition(
        id="ascrs-escp",
        name="ASCRS / ESCP Guidelines & Updates",
        source_type="society",
        base_url="https://fascrs.org/healthcare-providers/education/clinical-practice-guidelines",
        terms_reviewed_at="2026-11-27",
        poll_interval_minutes=720,
        trust_tier="tier1",
        enabled=False,
        default_domains=("minimally-invasive-surgery", "colorectal-oncology"),
        geography="global",
    ),
    SourceDefinition(
        id="clinicaltrials-gov",
        name="ClinicalTrials.gov API v2 (CRS)",
        source_type="trial_registry",
        base_url="https://clinicaltrials.gov/api/v2/studies?query.cond=colorectal+cancer&pageSize=20",
        terms_reviewed_at="2026-11-27",
        poll_interval_minutes=720,
        trust_tier="tier1",
        enabled=False,
        default_domains=("colorectal-oncology",),
        geography="global",
    ),
    SourceDefinition(
        id="tw-crs-society",
        name="中華民國大腸直腸外科醫學會（TSCRS）",
        source_type="society",
        base_url="https://www.crs.org.tw/",
        terms_reviewed_at="2026-11-27",
        poll_interval_minutes=720,
        trust_tier="tier1",
        enabled=False,
        default_domains=("colorectal-oncology", "minimally-invasive-surgery"),
        geography="taiwan",
    ),
    SourceDefinition(
        id="eras-esge",
        name="ERAS Society / ESGE Guidelines",
        source_type="guideline",
        base_url="https://erassociety.org/guidelines/",
        terms_reviewed_at="2026-11-27",
        poll_interval_minutes=1440,
        trust_tier="tier1",
        enabled=False,
        default_domains=("perioperative-care-nutrition", "endoscopy"),
        geography="eu",
    ),
)


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    body: bytes
    content_type: str = ""
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


@dataclass
class SourceHealth:
    source_id: str
    ok: bool
    items_collected: int = 0
    last_success_at: str | None = None
    last_error: str | None = None
    last_error_at: str | None = None


@dataclass(frozen=True)
class CandidateEvent:
    source_id: str
    title: str
    canonical_url: str
    event_type: str
    milestone_stage: str
    dedup_key: str
    published_at: str | None = None
    event_date: str | None = None
    effective_date: str | None = None
    external_id: str | None = None
    primary_domain_hint: str | None = None
    secondary_domain_hints: tuple[str, ...] = ()
    geography: str = "global"
    raw_metadata: dict[str, Any] = field(default_factory=dict)


# --- SSRF-hardened HTTP fetcher ------------------------------------------------------------------------------------

type Resolver = Callable[[str, int], list[str]]


def _is_forbidden_ip(raw_ip: str) -> bool:
    ip = ipaddress.ip_address(raw_ip)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def _default_resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips: list[str] = []
    for info in infos:
        addr = str(info[4][0])
        if addr not in ips:
            ips.append(addr)
    return ips


def validate_safe_url(url: str, *, resolver: Resolver = _default_resolve) -> tuple[urllib.parse.ParseResult, list[str]]:
    """Enforce HTTPS-only URLs and reject private, loopback, link-local, and cloud-metadata IPs."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() != "https":
        raise SSRFFetchError(f"only https:// URLs are allowed, got {parsed.scheme!r}")
    if not parsed.hostname:
        raise SSRFFetchError("URL missing hostname")
    if parsed.username or parsed.password:
        raise SSRFFetchError("URL credentials are forbidden")
    port = parsed.port or 443
    if port not in (443, 8443):
        raise SSRFFetchError(f"port {port} is not allowed")

    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
        resolved = [host]
    except ValueError:
        try:
            resolved = resolver(host, port)
        except OSError as exc:
            raise SSRFFetchError(f"DNS resolution failed for {host!r}: {exc}") from exc

    if not resolved:
        raise SSRFFetchError(f"DNS returned no addresses for {host!r}")
    for ip_str in resolved:
        if _is_forbidden_ip(ip_str):
            raise SSRFFetchError(f"blocked private/metadata IP {ip_str} for host {host!r}")
    return parsed, resolved


def safe_fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_RESPONSE_BYTES,
    max_redirects: int = MAX_REDIRECTS,
    etag: str | None = None,
    last_modified: str | None = None,
    retries: int = 2,
    resolver: Resolver = _default_resolve,
    opener: Callable[[urllib.parse.ParseResult, dict[str, str], float], tuple[int, dict[str, str], bytes]]
    | None = None,
) -> FetchResult:
    """Fetch an HTTPS resource with SSRF validation on every redirect hop, size caps, conditional GET, and retries."""
    current_url = url
    headers = {"User-Agent": "GutHub-Newsroom/1.0 (+https://guthub.tw)", "Accept": "*/*"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    for hop in range(max_redirects + 1):
        parsed, _ = validate_safe_url(current_url, resolver=resolver)
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                if opener is not None:
                    status, resp_headers, raw = opener(parsed, headers, timeout)
                    if len(raw) > max_bytes:
                        raise ResponseTooLargeError(f"response exceeded {max_bytes} bytes limit")
                else:
                    status, resp_headers, raw = _https_request(parsed, headers, timeout, max_bytes)
                break
            except (SSRFFetchError, ResponseTooLargeError):
                raise
            except OSError as exc:
                last_exc = exc
                if attempt >= retries:
                    raise
                time.sleep(0.5 * (attempt + 1))
        else:  # pragma: no cover
            raise RuntimeError(f"fetch failed: {last_exc}")

        lower_headers = {k.lower(): v for k, v in resp_headers.items()}
        if status == 304:
            return FetchResult(
                url=current_url,
                status=304,
                body=b"",
                etag=lower_headers.get("etag"),
                last_modified=lower_headers.get("last-modified"),
                not_modified=True,
            )
        if status in (301, 302, 303, 307, 308):
            location = lower_headers.get("location")
            if not location:
                raise SSRFFetchError(f"redirect {status} missing Location header")
            if hop >= max_redirects:
                raise SSRFFetchError(f"exceeded max redirects ({max_redirects})")
            current_url = urllib.parse.urljoin(current_url, location)
            continue
        if status in (429, 500, 502, 503, 504):
            raise OSError(f"upstream HTTP {status} from {current_url}")
        if status >= 400:
            raise RuntimeError(f"HTTP {status} from {current_url}")
        return FetchResult(
            url=current_url,
            status=status,
            body=raw,
            content_type=lower_headers.get("content-type", ""),
            etag=lower_headers.get("etag"),
            last_modified=lower_headers.get("last-modified"),
        )
    raise SSRFFetchError(f"exceeded max redirects ({max_redirects})")


def _https_request(
    parsed: urllib.parse.ParseResult,
    headers: dict[str, str],
    timeout: float,
    max_bytes: int,
) -> tuple[int, dict[str, str], bytes]:
    host = parsed.hostname or ""
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(host, port=port, timeout=timeout, context=ctx)
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        resp_headers = dict(resp.getheaders())
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ResponseTooLargeError(f"response exceeded {max_bytes} bytes limit")
            chunks.append(chunk)
        return resp.status, resp_headers, b"".join(chunks)
    finally:
        conn.close()


# --- Deterministic event deduplication -----------------------------------------------------------------------------


def canonicalize_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    kept_query = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in _TRACKING_PARAMS
    ]
    kept_query.sort()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urllib.parse.urlunparse(
        (
            parsed.scheme.lower(),
            (parsed.hostname or "").lower() + (f":{parsed.port}" if parsed.port not in (None, 443) else ""),
            path,
            "",
            urllib.parse.urlencode(kept_query),
            "",
        )
    )


def make_dedup_key(
    *,
    canonical_url: str,
    event_type: str,
    milestone_stage: str = "announcement",
    doi: str | None = None,
    pmid: str | None = None,
    nct_id: str | None = None,
    external_id: str | None = None,
) -> str:
    """Deterministic dedup key preserving distinct trial milestones (recruitment vs results vs correction)."""
    if doi:
        anchor = f"doi:{doi.strip().lower()}"
    elif pmid:
        anchor = f"pmid:{pmid.strip()}"
    elif nct_id:
        anchor = f"nct:{nct_id.strip().upper()}"
    elif external_id:
        anchor = f"ext:{external_id.strip().lower()}"
    else:
        anchor = f"url:{canonicalize_url(canonical_url)}"
    basis = f"{anchor}|{event_type.strip().lower()}|{milestone_stage.strip().lower()}"
    return f"evt:{hashlib.sha256(basis.encode('utf-8')).hexdigest()[:32]}"


def deduplicate_events(events: list[CandidateEvent]) -> list[CandidateEvent]:
    """Keep the first occurrence of each deterministic dedup_key while preserving order."""
    seen: set[str] = set()
    out: list[CandidateEvent] = []
    for ev in events:
        if ev.dedup_key not in seen:
            seen.add(ev.dedup_key)
            out.append(ev)
    return out


# --- Direct source adapters (initial 6 sources) --------------------------------------------------------------------


def _strip_html(raw: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG_RE.sub(" ", raw))).strip()


def _parse_iso_date(raw: str | None) -> str | None:
    if not raw:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
    if m:
        return m.group(1)
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _extract_identifiers(text: str) -> tuple[str | None, str | None]:
    doi_m = _DOI_RE.search(text)
    nct_m = _NCT_RE.search(text)
    return (doi_m.group(1).rstrip(".,;)") if doi_m else None, nct_m.group(1).upper() if nct_m else None)


def parse_regulatory_watch_findings(findings: list[Any]) -> list[CandidateEvent]:
    """Bridge existing G5 scripts/regulatory_watch.py findings into Newsroom CandidateEvents."""
    events: list[CandidateEvent] = []
    for f in findings:
        title = str(getattr(f, "title", "")).strip()
        body = str(getattr(f, "body", "")).strip()
        if not title:
            continue
        url_m = re.search(r"(https://[^\s)>\"]+)", body)
        url = url_m.group(1) if url_m else "https://info.nhi.gov.tw/"
        canon = canonicalize_url(url)
        stage = "nhi_clause_update" if "健保" in title else "tfda_licence_change"
        dedup_key = make_dedup_key(
            canonical_url=canon,
            event_type="regulatory",
            milestone_stage=stage,
            external_id=f"tw-reg:{title}",
        )
        events.append(
            CandidateEvent(
                source_id="tw-nhi-tfda",
                title=title,
                canonical_url=canon,
                event_type="regulatory",
                milestone_stage=stage,
                dedup_key=dedup_key,
                primary_domain_hint="colorectal-oncology",
                geography="taiwan",
                raw_metadata={"body_excerpt": body[:600]},
            )
        )
    return events


def parse_fda_oncology_feed(xml_bytes: bytes) -> list[CandidateEvent]:
    """Parse FDA Drug/Oncology RSS feed, keeping strictly colorectal/rectal/anal cancer approvals."""
    root = ET.fromstring(xml_bytes)
    events: list[CandidateEvent] = []
    for item in root.findall(".//item"):
        title = _strip_html(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        desc = _strip_html(item.findtext("description") or "")
        pub_date = _parse_iso_date(item.findtext("pubDate"))
        if not title or not link.startswith("https://"):
            continue
        if not _CRC_RE.search(f"{title} {desc}"):
            continue
        canon = canonicalize_url(link)
        doi, nct = _extract_identifiers(f"{title} {desc}")
        stage = "safety" if "safety" in title.lower() or "warning" in title.lower() else "approval"
        ev_type = "safety" if stage == "safety" else "regulatory"
        events.append(
            CandidateEvent(
                source_id="fda-oncology",
                title=title,
                canonical_url=canon,
                event_type=ev_type,
                milestone_stage=stage,
                dedup_key=make_dedup_key(
                    canonical_url=canon, event_type=ev_type, milestone_stage=stage, doi=doi, nct_id=nct
                ),
                published_at=pub_date,
                event_date=pub_date,
                primary_domain_hint="colorectal-oncology",
                geography="us",
                raw_metadata={"summary": desc[:500]},
            )
        )
    return events


def parse_clinicaltrials_v2(
    json_bytes: bytes,
    *,
    previous_states: dict[str, dict[str, Any]] | None = None,
) -> list[CandidateEvent]:
    """Parse ClinicalTrials.gov API v2 studies, ignoring routine administrative/contact edits."""
    data = json.loads(json_bytes.decode("utf-8"))
    studies = data.get("studies") or []
    prev_map = previous_states or {}
    events: list[CandidateEvent] = []

    for study in studies:
        proto = study.get("protocolSection") or {}
        ident = proto.get("identificationModule") or {}
        status_mod = proto.get("statusModule") or {}
        nct_id = str(ident.get("nctId") or "").strip().upper()
        title = str(ident.get("briefTitle") or ident.get("officialTitle") or "").strip()
        overall_status = str(status_mod.get("overallStatus") or "").strip().upper()
        has_results = bool(study.get("hasResults"))
        last_update = _parse_iso_date((status_mod.get("lastUpdatePostDateStruct") or {}).get("date"))
        results_posted = _parse_iso_date((status_mod.get("resultsFirstPostDateStruct") or {}).get("date"))

        if not nct_id or not title:
            continue

        prev = prev_map.get(nct_id)
        # Routine administrative update (contact/location/date tweak without status or results change): skip!
        if (
            prev is not None
            and prev.get("overallStatus") == overall_status
            and bool(prev.get("hasResults")) == has_results
        ):
            continue

        if has_results:
            stage = "primary_results"
        elif overall_status in ("TERMINATED", "SUSPENDED", "WITHDRAWN"):
            stage = f"status_{overall_status.lower()}"
        elif overall_status == "COMPLETED":
            stage = "completed"
        elif overall_status == "RECRUITING" and prev is None:
            stage = "recruitment"
        else:
            # Skip non-substantive statuses like NOT_YET_RECRUITING or routine ACTIVE_NOT_RECRUITING pings.
            continue

        canon = f"https://clinicaltrials.gov/study/{nct_id}"
        events.append(
            CandidateEvent(
                source_id="clinicaltrials-gov",
                title=f"{nct_id}: {title}",
                canonical_url=canon,
                event_type="trial",
                milestone_stage=stage,
                dedup_key=make_dedup_key(
                    canonical_url=canon,
                    event_type="trial",
                    milestone_stage=stage,
                    nct_id=nct_id,
                ),
                published_at=results_posted or last_update,
                event_date=results_posted or last_update,
                external_id=nct_id,
                primary_domain_hint="colorectal-oncology",
                geography="global",
                raw_metadata={"nctId": nct_id, "overallStatus": overall_status, "hasResults": has_results},
            )
        )
    return events


def parse_society_rss_or_html(
    body: bytes,
    *,
    source_id: str,
    base_url: str,
    geography: str,
    default_domain: str,
) -> list[CandidateEvent]:
    """Parse RSS/Atom XML or anchor-list HTML for ASCRS/ESCP, TSCRS (crs.org.tw), and ERAS/ESGE."""
    text = body.decode("utf-8", errors="replace").strip()
    events: list[CandidateEvent] = []

    if text.startswith("<?xml") or "<rss" in text[:400].lower() or "<feed" in text[:400].lower():
        root = ET.fromstring(body)
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        for item in items:
            title = _strip_html(item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "")
            link = (item.findtext("link") or "").strip()
            if not link:
                link_el = item.find("{http://www.w3.org/2005/Atom}link")
                link = (link_el.get("href") or "").strip() if link_el is not None else ""
            pub = _parse_iso_date(
                item.findtext("pubDate")
                or item.findtext("{http://www.w3.org/2005/Atom}updated")
                or item.findtext("{http://www.w3.org/2005/Atom}published")
            )
            if not title or not link:
                continue
            full_url = urllib.parse.urljoin(base_url, link)
            if not full_url.startswith("https://"):
                continue
            canon = canonicalize_url(full_url)
            domain = _infer_specialty_hint(title, default_domain)
            ev_type = "guideline" if "guideline" in title.lower() or "指引" in title else "society"
            events.append(
                CandidateEvent(
                    source_id=source_id,
                    title=title,
                    canonical_url=canon,
                    event_type=ev_type,
                    milestone_stage="announcement",
                    dedup_key=make_dedup_key(canonical_url=canon, event_type=ev_type),
                    published_at=pub,
                    event_date=pub,
                    primary_domain_hint=domain,
                    geography=geography,
                )
            )
        return events

    # Minimal anchor extraction for society news/guidelines HTML pages (e.g., crs.org.tw / erassociety.org).
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.IGNORECASE | re.DOTALL):
        href, label = m.group(1).strip(), _strip_html(m.group(2))
        if len(label) < 8 or href.startswith("#") or href.startswith("mailto:"):
            continue
        full_url = urllib.parse.urljoin(base_url, href)
        if not full_url.startswith("https://"):
            continue
        if not re.search(
            r"guideline|consensus|news|notice|annual|會議|指引|公告|eras|esge|ascrs|escp|大腸",
            f"{href} {label}",
            re.IGNORECASE,
        ):
            continue
        canon = canonicalize_url(full_url)
        domain = _infer_specialty_hint(label, default_domain)
        ev_type = "guideline" if re.search(r"guideline|consensus|指引", label, re.IGNORECASE) else "society"
        events.append(
            CandidateEvent(
                source_id=source_id,
                title=label,
                canonical_url=canon,
                event_type=ev_type,
                milestone_stage="announcement",
                dedup_key=make_dedup_key(canonical_url=canon, event_type=ev_type),
                primary_domain_hint=domain,
                geography=geography,
            )
        )
    return deduplicate_events(events)


def _infer_specialty_hint(text: str, default_domain: str) -> str:
    if _ENDO_RE.search(text):
        return "endoscopy"
    if _PERIO_RE.search(text):
        return "perioperative-care-nutrition"
    return default_domain


# --- Fault-isolated collector runner -------------------------------------------------------------------------------


def collect_sources(
    sources: tuple[SourceDefinition, ...] = INITIAL_SOURCES,
    *,
    fetcher: Callable[[str], FetchResult] | None = None,
    regulatory_findings_fn: Callable[[], list[Any]] | None = None,
) -> tuple[list[CandidateEvent], list[SourceHealth]]:
    """Run all enabled sources with per-source fault isolation and health reporting."""
    fetch_fn = fetcher or (lambda url: safe_fetch(url))
    all_events: list[CandidateEvent] = []
    health_reports: list[SourceHealth] = []
    now_iso = datetime.now(UTC).isoformat()

    for src in sources:
        if not src.enabled:
            continue
        try:
            if src.id == "tw-nhi-tfda":
                items = parse_regulatory_watch_findings(regulatory_findings_fn() if regulatory_findings_fn else [])
            else:
                res = fetch_fn(src.base_url)
                if res.not_modified:
                    items = []
                elif src.id == "fda-oncology":
                    items = parse_fda_oncology_feed(res.body)
                elif src.id == "clinicaltrials-gov":
                    items = parse_clinicaltrials_v2(res.body)
                else:
                    default_domain = src.default_domains[0] if src.default_domains else "colorectal-oncology"
                    items = parse_society_rss_or_html(
                        res.body,
                        source_id=src.id,
                        base_url=src.base_url,
                        geography=src.geography,
                        default_domain=default_domain,
                    )
            all_events.extend(items)
            health_reports.append(
                SourceHealth(
                    source_id=src.id,
                    ok=True,
                    items_collected=len(items),
                    last_success_at=now_iso,
                )
            )
        except Exception as exc:
            health_reports.append(
                SourceHealth(
                    source_id=src.id,
                    ok=False,
                    items_collected=0,
                    last_error=str(exc)[:500],
                    last_error_at=now_iso,
                )
            )

    return deduplicate_events(all_events), health_reports


def sync_source_registry(conn: Any, sources: tuple[SourceDefinition, ...] = INITIAL_SOURCES) -> int:
    """Seed/update app.news_source_registry metadata without overwriting enabled flags set by the maintainer."""
    count = 0
    with conn.transaction(), conn.cursor() as cur:
        for src in sources:
            cur.execute(
                "insert into app.news_source_registry"
                " (id, name, source_type, base_url, terms_reviewed_at, poll_interval_minutes, trust_tier, enabled)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s)"
                " on conflict (id) do update set"
                " name = excluded.name, source_type = excluded.source_type, base_url = excluded.base_url,"
                " terms_reviewed_at = excluded.terms_reviewed_at, poll_interval_minutes = excluded.poll_interval_minutes,"
                " trust_tier = excluded.trust_tier, updated_at = now()",
                (
                    src.id,
                    src.name,
                    src.source_type,
                    src.base_url,
                    src.terms_reviewed_at,
                    src.poll_interval_minutes,
                    src.trust_tier,
                    src.enabled,
                ),
            )
            count += 1
    return count
