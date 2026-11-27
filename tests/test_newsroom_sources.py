"""Tests for N2 #287: 6 initial direct sources, SSRF defense, deterministic dedup, and fault isolation."""

import json
from dataclasses import dataclass

import pytest
from newsroom.sources import (
    INITIAL_SOURCES,
    CandidateEvent,
    FetchResult,
    ResponseTooLargeError,
    SourceDefinition,
    SSRFFetchError,
    canonicalize_url,
    collect_sources,
    deduplicate_events,
    make_dedup_key,
    parse_clinicaltrials_v2,
    parse_fda_oncology_feed,
    parse_regulatory_watch_findings,
    parse_society_rss_or_html,
    safe_fetch,
    validate_safe_url,
)


def _public_resolver(host: str, _port: int) -> list[str]:
    if host == "metadata.internal":
        return ["169.254.169.254"]
    if host == "private.corp":
        return ["10.0.1.5"]
    if host == "localhost.evil":
        return ["127.0.0.1"]
    return ["93.184.216.34"]


def test_initial_six_sources_have_terms_and_disabled_by_default() -> None:
    ids = [s.id for s in INITIAL_SOURCES]
    assert ids == [
        "tw-nhi-tfda",
        "fda-oncology",
        "ascrs-escp",
        "clinicaltrials-gov",
        "tw-crs-society",
        "eras-esge",
    ]
    for src in INITIAL_SOURCES:
        assert src.base_url.startswith("https://")
        assert src.terms_reviewed_at == "2026-11-27"
        assert src.enabled is False


def test_ssrf_blocks_non_https_private_metadata_and_redirect_to_metadata() -> None:
    for bad_url in (
        "http://www.fda.gov/drugs",
        "file:///etc/passwd",
        "https://127.0.0.1/admin",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1]/secret",
        "https://metadata.internal/token",
        "https://private.corp/db",
        "https://localhost.evil/api",
        "https://user:pass@example.com/",
    ):
        with pytest.raises(SSRFFetchError):
            validate_safe_url(bad_url, resolver=_public_resolver)

    # Redirect hop to AWS/GCP cloud metadata IP must be blocked before opening hop 2.
    def redirect_to_metadata(_parsed, _headers, _timeout):
        return 302, {"Location": "https://169.254.169.254/computeMetadata/v1/"}, b""

    with pytest.raises(SSRFFetchError, match="blocked private/metadata IP"):
        safe_fetch("https://example.com/start", resolver=_public_resolver, opener=redirect_to_metadata)

    # Response size limit must abort oversized bodies.
    def oversized(_parsed, _headers, _timeout):
        return 200, {"Content-Type": "text/plain"}, b"x" * 2048

    with pytest.raises(ResponseTooLargeError):
        safe_fetch("https://example.com/big", max_bytes=1024, resolver=_public_resolver, opener=oversized)


def test_six_source_adapters_parse_fixtures_and_filter_noise() -> None:
    # 1. Taiwan NHI / TFDA bridge from regulatory_watch.Finding
    @dataclass
    class FakeFinding:
        title: str
        body: str

    reg_events = parse_regulatory_watch_findings(
        [
            FakeFinding(
                title="[G5 監測] 健保給付規定 9.134. 有新版 20261201",
                body="PDF: https://info.nhi.gov.tw/api/INAE3000/INAE3000S01/getPDF?DurgFileName=9.134._20261201.pdf",
            )
        ]
    )
    assert len(reg_events) == 1
    assert reg_events[0].geography == "taiwan"
    assert reg_events[0].milestone_stage == "nhi_clause_update"

    # 2. FDA Oncology RSS keeps CRC, filters out non-CRC lung cancer
    fda_xml = b"""<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>FDA approves encorafenib combination for BRAF V600E metastatic colorectal cancer</title>
        <link>https://www.fda.gov/drugs/mcrc-2026?utm_source=rss</link>
        <pubDate>Thu, 26 Nov 2026 00:00:00 GMT</pubDate>
        <description>First-line mCRC approval.</description>
      </item>
      <item>
        <title>FDA approves osimertinib for non-small cell lung cancer</title>
        <link>https://www.fda.gov/drugs/nsclc-2026</link>
        <pubDate>Thu, 26 Nov 2026 00:00:00 GMT</pubDate>
        <description>NSCLC indication.</description>
      </item>
    </channel></rss>"""
    fda_events = parse_fda_oncology_feed(fda_xml)
    assert len(fda_events) == 1
    assert fda_events[0].canonical_url == "https://www.fda.gov/drugs/mcrc-2026"

    # 3. ClinicalTrials.gov v2 keeps substantive results & skips routine admin metadata edit
    ct_payload = json.dumps(
        {
            "studies": [
                {
                    "hasResults": True,
                    "protocolSection": {
                        "identificationModule": {"nctId": "NCT04607421", "briefTitle": "BREAKWATER mCRC"},
                        "statusModule": {
                            "overallStatus": "ACTIVE_NOT_RECRUITING",
                            "resultsFirstPostDateStruct": {"date": "2026-11-20"},
                        },
                    },
                },
                {
                    "hasResults": False,
                    "protocolSection": {
                        "identificationModule": {"nctId": "NCT00000002", "briefTitle": "Admin edit trial"},
                        "statusModule": {
                            "overallStatus": "RECRUITING",
                            "lastUpdatePostDateStruct": {"date": "2026-11-25"},
                        },
                    },
                },
            ]
        }
    ).encode()
    ct_events = parse_clinicaltrials_v2(
        ct_payload,
        previous_states={"NCT00000002": {"overallStatus": "RECRUITING", "hasResults": False}},
    )
    assert [e.external_id for e in ct_events] == ["NCT04607421"]
    assert ct_events[0].milestone_stage == "primary_results"

    # 4-6. ASCRS/ESCP, TSCRS (crs.org.tw), ERAS/ESGE
    eras_html = b"""<html><body>
      <a href="/guidelines/colorectal-2026/">Updated ERAS Colorectal Surgery Guideline 2026</a>
      <a href="/guidelines/esd-2026/">ESGE Colorectal ESD Consensus Update</a>
    </body></html>"""
    eras_events = parse_society_rss_or_html(
        eras_html,
        source_id="eras-esge",
        base_url="https://erassociety.org/guidelines/",
        geography="eu",
        default_domain="perioperative-care-nutrition",
    )
    assert len(eras_events) == 2
    assert {e.primary_domain_hint for e in eras_events} == {"perioperative-care-nutrition", "endoscopy"}

    tscrs_html = (
        '<html><body><a href="/news/annual-2026">2026 大腸直腸外科醫學會年會最新指引公告</a></body></html>'.encode()
    )
    tscrs_events = parse_society_rss_or_html(
        tscrs_html,
        source_id="tw-crs-society",
        base_url="https://www.crs.org.tw/",
        geography="taiwan",
        default_domain="colorectal-oncology",
    )
    assert len(tscrs_events) == 1
    assert tscrs_events[0].geography == "taiwan"


def test_deterministic_dedup_preserves_distinct_trial_milestones() -> None:
    assert canonicalize_url("https://Example.com/news/1/?utm_source=x&id=2#top") == "https://example.com/news/1?id=2"

    k_recruit = make_dedup_key(
        canonical_url="https://clinicaltrials.gov/study/NCT04607421",
        event_type="trial",
        milestone_stage="recruitment",
        nct_id="NCT04607421",
    )
    k_results = make_dedup_key(
        canonical_url="https://clinicaltrials.gov/study/NCT04607421",
        event_type="trial",
        milestone_stage="primary_results",
        nct_id="NCT04607421",
    )
    k_correction = make_dedup_key(
        canonical_url="https://clinicaltrials.gov/study/NCT04607421",
        event_type="trial",
        milestone_stage="correction",
        nct_id="NCT04607421",
    )
    assert len({k_recruit, k_results, k_correction}) == 3

    dup_list = [
        CandidateEvent(
            "clinicaltrials-gov",
            "Trial",
            "https://clinicaltrials.gov/study/NCT04607421",
            "trial",
            "primary_results",
            k_results,
        ),
        CandidateEvent(
            "clinicaltrials-gov",
            "Trial dup",
            "https://clinicaltrials.gov/study/NCT04607421",
            "trial",
            "primary_results",
            k_results,
        ),
        CandidateEvent(
            "clinicaltrials-gov",
            "Trial corr",
            "https://clinicaltrials.gov/study/NCT04607421",
            "trial",
            "correction",
            k_correction,
        ),
    ]
    assert len(deduplicate_events(dup_list)) == 2


def test_single_source_failure_does_not_block_other_sources() -> None:
    sources = (
        SourceDefinition(
            "fda-oncology", "FDA", "regulatory", "https://fda.example/rss", "2026-11-27", 360, "tier1", enabled=True
        ),
        SourceDefinition(
            "eras-esge",
            "ERAS",
            "guideline",
            "https://eras.example/g",
            "2026-11-27",
            360,
            "tier1",
            enabled=True,
            default_domains=("perioperative-care-nutrition",),
        ),
    )

    def flaky_fetcher(url: str) -> FetchResult:
        if "fda.example" in url:
            raise OSError("connection timed out")
        return FetchResult(
            url=url,
            status=200,
            body=b'<a href="https://eras.example/2026">Updated ERAS Guideline for Colorectal Surgery</a>',
        )

    events, reports = collect_sources(sources, fetcher=flaky_fetcher)
    assert len(events) == 1
    by_id = {r.source_id: r for r in reports}
    assert by_id["fda-oncology"].ok is False and "timed out" in (by_id["fda-oncology"].last_error or "")
    assert by_id["eras-esge"].ok is True and by_id["eras-esge"].last_success_at is not None
