"""Push subscriptions and announcements against the real database (C5 #95). Needs GUTHUB_TEST_DATABASE_URL; skips
without it unless GUTHUB_REQUIRE_DB=1."""

import json
import os
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

import psycopg
import pytest
import requests
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pywebpush import WebPushException

from guthub_api import maintenance
from guthub_api.announce import Subscription, announce_news
from guthub_api.main import API_PREFIX, create_app
from guthub_api.settings import Settings

DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")
if not DB_URL:
    if os.environ.get("GUTHUB_REQUIRE_DB") == "1":
        raise RuntimeError("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
    pytest.skip("GUTHUB_TEST_DATABASE_URL not set", allow_module_level=True)
API_DB_URL = f"{DB_URL}{'&' if '?' in DB_URL else '?'}options={quote('-c role=guthub_api')}"
# A real P-256 point: the API parses the key, so a string of the right shape is not enough.
P256DH = "BEq92_TdZHWFumPXL2bSHnBMqQBmT_W8m21dM7uY3rkkXPMVrQbusl5OczVDTV0mymDHq9gvO-BlkPCo5biR1do"
AUTH = "c" * 22


def sql(statement: Any, params: Any = None) -> list[Any]:
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        cur = conn.execute(statement, params)
        return cur.fetchall() if cur.description else []


def endpoint(name: str) -> str:
    return f"https://fcm.googleapis.com/fcm/send/c5-test-{name}"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(Settings(environment="test", database_url=SecretStr(API_DB_URL)))) as client:
        yield client
    sql("delete from app.push_subscriptions where endpoint like '%c5-test-%'")


@pytest.fixture
def stories() -> Iterator[dict[str, str]]:
    run = uuid.uuid4().hex[:8]
    paper = f"c5-{run}"
    sql("insert into app.topics (key, slug, label, title) values ('mCRC-MSI-H', 'msi-h', 'MSI-H', 'MSI-H mCRC')"
        " on conflict do nothing")  # fmt: skip
    sql(
        "insert into app.papers (id, slug, topic_key, year, journal, study_type, regimen, endpoint, result, bottom_line,"
        " source, reviewed_at, detail_html) values (%s, %s, 'mCRC-MSI-H', 2026, 'NEJM', 'Phase 3 RCT', 'Drug', 'OS',"
        " 'HR 0.5', 'Use it', 'fulltext', '2026-11-01', '<p>x</p>')",
        (paper, paper),
    )
    ids = {"fresh": f"c5-fresh-{run}", "old": f"c5-old-{run}"}
    for name, days in (("fresh", 0), ("old", 10)):
        sql(
            "insert into app.news (id, paper_id, published_at, headline, dek, key, body, review_status)"
            " values (%s, %s, current_date - %s, %s, 'dek', '{}', '[]', 'auto')",
            (ids[name], paper, days, json.dumps([f"{name} ", "headline"])),
        )
    # Only this test's stories count: anything else in the database is treated as already announced.
    sql("insert into app.push_announcements (news_id, sent, removed, failed) select id, 0, 0, 0 from app.news"
        " where id not in (%s, %s) on conflict do nothing", (ids["fresh"], ids["old"]))  # fmt: skip
    yield ids
    sql("delete from app.push_announcements where news_id = any(%s)", (list(ids.values()),))
    sql("delete from app.news where paper_id = %s", (paper,))
    sql("delete from app.papers where id = %s", (paper,))
    sql("delete from app.push_subscriptions where endpoint like '%c5-test-%'")


def subscription(name: str, **keys: str) -> dict[str, Any]:
    return {"endpoint": endpoint(name), "keys": {"p256dh": keys.get("p256dh", P256DH), "auth": keys.get("auth", AUTH)}}


# --- subscriptions through the API ----------------------------------------------------------------------------------


def test_subscribe_renew_and_unsubscribe(client: TestClient) -> None:
    url = f"{API_PREFIX}/push/subscription"
    first = client.put(url, json=subscription("phone"))
    assert first.status_code == 204
    assert first.headers["cache-control"] == "no-store"
    assert client.put(url, json=subscription("phone", auth="d" * 22)).status_code == 204
    assert sql("select auth from app.push_subscriptions where endpoint = %s", (endpoint("phone"),)) == [("d" * 22,)]
    assert client.request("DELETE", url, json={"endpoint": endpoint("phone")}).status_code == 204
    assert sql("select 1 from app.push_subscriptions where endpoint = %s", (endpoint("phone"),)) == []
    # Unknown endpoints answer the same, so the call says nothing about other browsers.
    assert client.request("DELETE", url, json={"endpoint": endpoint("never")}).status_code == 204


@pytest.mark.parametrize(
    "body",
    [
        {"endpoint": "https://evil.example/push/1", "keys": {"p256dh": P256DH, "auth": AUTH}},
        {"endpoint": "http://fcm.googleapis.com/fcm/send/x", "keys": {"p256dh": P256DH, "auth": AUTH}},
        {"endpoint": "https://fcm.googleapis.com.evil.example/x", "keys": {"p256dh": P256DH, "auth": AUTH}},
        {"endpoint": endpoint("x" * 2100), "keys": {"p256dh": P256DH, "auth": AUTH}},
        {"endpoint": endpoint("x"), "keys": {"p256dh": "not base64!", "auth": AUTH}},
        {"endpoint": endpoint("x"), "keys": {"p256dh": P256DH, "auth": "short"}},
        # Right shape, not a point on the curve: would make the sender's encryption fail for everyone after it.
        {"endpoint": endpoint("x"), "keys": {"p256dh": "B" + "A" * 86, "auth": AUTH}},
        {"endpoint": endpoint("x"), "keys": {"p256dh": P256DH, "auth": "c" * 23}},
        {"endpoint": endpoint("x"), "keys": {"p256dh": P256DH, "auth": AUTH}, "account": "someone"},
    ],
)
def test_subscriptions_must_point_at_a_real_push_service(client: TestClient, body: dict[str, Any]) -> None:
    assert client.put(f"{API_PREFIX}/push/subscription", json=body).status_code == 422
    assert sql("select count(*) from app.push_subscriptions where endpoint like '%c5-test-%'") == [(0,)]


# --- announcing stories -----------------------------------------------------------------------------------------------


class FakePush:
    """Records deliveries; endpoints named gone or broken fail the way push services do."""

    def __init__(self) -> None:
        self.delivered: list[tuple[str, dict[str, str], str]] = []

    def __call__(self, sub: Subscription, data: str, topic: str) -> None:
        if sub.endpoint.endswith("unusable"):  # fails before reaching any push service, e.g. a key that cannot encrypt
            raise ValueError("invalid key")
        if sub.endpoint.endswith("offline"):  # the network to the push service failed: says nothing about the browser
            raise requests.ConnectionError("timed out")
        status = 410 if sub.endpoint.endswith("gone") else 500 if sub.endpoint.endswith("broken") else None
        if status:
            raise WebPushException("push failed", response=SimpleNamespace(status_code=status))
        self.delivered.append((sub.endpoint, json.loads(data), topic))


def test_a_fresh_story_is_announced_once_and_gone_browsers_are_dropped(stories: dict[str, str]) -> None:
    # "unusable" sorts first, so the rest are sent only if its failure does not stop the job.
    for name in ("phone", "gone", "broken", "a-unusable", "offline"):
        sql(
            "insert into app.push_subscriptions (endpoint, p256dh, auth) values (%s, %s, %s)",
            (endpoint(name), P256DH, AUTH),
        )
    push = FakePush()

    assert announce_news(API_DB_URL, push) == {"stories": 1, "sent": 1, "removed": 2, "failed": 2}
    assert push.delivered == [
        (
            endpoint("phone"),
            {"title": "fresh headline", "body": "dek", "url": f"/news/{stories['fresh']}/", "tag": stories["fresh"]},
            stories["fresh"],
        )
    ]
    assert sql("select endpoint from app.push_subscriptions where endpoint like '%c5-test-%' order by 1") == [
        (endpoint("broken"),),
        (endpoint("offline"),),
        (endpoint("phone"),),
    ]
    assert sql("select sent, removed, failed from app.push_announcements where news_id = %s", (stories["fresh"],)) == [
        (1, 2, 2)
    ]
    # Reruns (the schedule, a rebuild, a deploy) send nothing more; the old story never qualified.
    assert announce_news(API_DB_URL, push) == {"stories": 0, "sent": 0, "removed": 0, "failed": 0}
    assert len(push.delivered) == 1
    assert sql("select 1 from app.push_announcements where news_id = %s", (stories["old"],)) == []


def test_announce_needs_the_vapid_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUTHUB_DATABASE_URL", API_DB_URL)
    monkeypatch.delenv("GUTHUB_VAPID_PRIVATE_KEY", raising=False)
    assert maintenance.main(["announce-news"]) == 1


def test_newsroom_event_web_push_is_gated_by_flag_and_deduplicated_on_rerun(
    stories: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """N7 #292: NEWSROOM_NOTIFY_ENABLED defaults OFF; when enabled, each published event pushes at most once."""
    run = uuid.uuid4().hex[:8]
    event_id = f"n7-push-{run}"
    draft_id = f"n7-push-draft-{run}"
    # Mark fixture legacy story already announced so only the Newsroom event is under test.
    sql(
        "insert into app.push_announcements (news_id, sent, removed, failed) values (%s, 0, 0, 0)"
        " on conflict do nothing",
        (stories["fresh"],),
    )
    sql(
        "insert into app.push_subscriptions (endpoint, p256dh, auth) values (%s, %s, %s)",
        (endpoint(f"n7-{run}"), P256DH, AUTH),
    )
    try:
        for eid, status in ((event_id, "published"), (draft_id, "draft")):
            sql(
                "insert into app.news_events"
                " (id, dedup_key, category, geography, evidence_status, risk_tier, status, review_status, published_at)"
                " values (%s, %s, 'regulatory', 'taiwan', 'approved', 'low', %s, 'reviewed', current_date)",
                (eid, f"dedup-{eid}", status),
            )
            [(rev_id,)] = sql(
                "insert into app.news_revisions"
                " (event_id, revision_number, headline, what_happened, why_it_matters,"
                "  clinical_relevance, evidence_limitations, created_by)"
                " values (%s, 1, 'TFDA 發布新警訊', '公告臨床注意事項', '影響處方判斷', '臨床關聯', '限制', 'test')"
                " returning id",
                (eid,),
            )
            sql("update app.news_events set current_revision_id = %s where id = %s", (rev_id, eid))

        monkeypatch.delenv("NEWSROOM_NOTIFY_ENABLED", raising=False)
        push = FakePush()
        # Default OFF: nothing sent and nothing claimed.
        assert announce_news(API_DB_URL, push) == {"stories": 0, "sent": 0, "removed": 0, "failed": 0}
        assert push.delivered == []

        # Explicitly enabled: published event is announced once; draft is never announced; rerun sends zero duplicates.
        monkeypatch.setenv("NEWSROOM_NOTIFY_ENABLED", "true")
        first = announce_news(API_DB_URL, push)
        assert first == {"stories": 1, "sent": 1, "removed": 0, "failed": 0}
        assert len(push.delivered) == 1
        assert push.delivered[0][1]["url"] == f"/news/events/{event_id}/"
        assert announce_news(API_DB_URL, push) == {"stories": 0, "sent": 0, "removed": 0, "failed": 0}
        assert len(push.delivered) == 1
        assert sql("select 1 from app.news_event_push_announcements where event_id = %s", (draft_id,)) == []
    finally:
        sql("delete from app.news_events where id = any(%s)", ([event_id, draft_id],))
        sql("delete from app.push_subscriptions where endpoint = %s", (endpoint(f"n7-{run}"),))
