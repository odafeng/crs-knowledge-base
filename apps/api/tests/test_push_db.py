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
P256DH = "B" + "A" * 86
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
        status = 410 if sub.endpoint.endswith("gone") else 500 if sub.endpoint.endswith("broken") else None
        if status:
            raise WebPushException("push failed", response=SimpleNamespace(status_code=status))
        self.delivered.append((sub.endpoint, json.loads(data), topic))


def test_a_fresh_story_is_announced_once_and_gone_browsers_are_dropped(stories: dict[str, str]) -> None:
    for name in ("phone", "gone", "broken"):
        sql(
            "insert into app.push_subscriptions (endpoint, p256dh, auth) values (%s, %s, %s)",
            (endpoint(name), P256DH, AUTH),
        )
    push = FakePush()

    assert announce_news(API_DB_URL, push) == {"stories": 1, "sent": 1, "removed": 1, "failed": 1}
    assert push.delivered == [
        (
            endpoint("phone"),
            {"title": "fresh headline", "body": "dek", "url": f"/news/{stories['fresh']}/", "tag": stories["fresh"]},
            stories["fresh"],
        )
    ]
    assert sql("select endpoint from app.push_subscriptions where endpoint like '%c5-test-%' order by 1") == [
        (endpoint("broken"),),
        (endpoint("phone"),),
    ]
    assert sql("select sent, removed, failed from app.push_announcements where news_id = %s", (stories["fresh"],)) == [
        (1, 1, 1)
    ]
    # Reruns (the schedule, a rebuild, a deploy) send nothing more; the old story never qualified.
    assert announce_news(API_DB_URL, push) == {"stories": 0, "sent": 0, "removed": 0, "failed": 0}
    assert len(push.delivered) == 1
    assert sql("select 1 from app.push_announcements where news_id = %s", (stories["old"],)) == []


def test_announce_needs_the_vapid_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUTHUB_DATABASE_URL", API_DB_URL)
    monkeypatch.delenv("GUTHUB_VAPID_PRIVATE_KEY", raising=False)
    assert maintenance.main(["announce-news"]) == 1
