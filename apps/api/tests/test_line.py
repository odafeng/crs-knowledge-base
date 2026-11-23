"""The LINE daily broadcast (G3 #114) against a mock LINE API and the real database. Needs GUTHUB_TEST_DATABASE_URL;
skips without it unless GUTHUB_REQUIRE_DB=1. No test sends a real message."""

import json
import os
import threading
import uuid
from collections.abc import Iterator
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import quote

import psycopg
import pytest

from guthub_api import maintenance
from guthub_api.line import broadcast_daily, message

DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")
if not DB_URL:
    if os.environ.get("GUTHUB_REQUIRE_DB") == "1":
        raise RuntimeError("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
    pytest.skip("GUTHUB_TEST_DATABASE_URL not set", allow_module_level=True)
API_DB_URL = f"{DB_URL}{'&' if '?' in DB_URL else '?'}options={quote('-c role=guthub_api')}"
ORIGIN = "https://guthub.tw"
TOKEN = "test-channel-token"


def sql(statement: Any, params: Any = None) -> list[Any]:
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        cur = conn.execute(statement, params)
        return cur.fetchall() if cur.description else []


class MockLine:
    """Answers like the Messaging API's broadcast endpoint, with scripted statuses; remembers retry keys it accepted."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.statuses: list[int] = []
        self.accepted: set[str] = set()

    def handler(self) -> type[BaseHTTPRequestHandler]:
        line = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                key = self.headers.get("X-Line-Retry-Key", "")
                line.requests.append(
                    {"path": self.path, "auth": self.headers.get("Authorization"), "key": key, "body": body}
                )
                status = line.statuses.pop(0) if line.statuses else (409 if key in line.accepted else 200)
                if status == 200:
                    line.accepted.add(key)
                self.send_response(status)
                self.send_header("content-length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        return Handler


@pytest.fixture
def line() -> Iterator[tuple[str, MockLine]]:
    mock = MockLine()
    server = ThreadingHTTPServer(("127.0.0.1", 0), mock.handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", mock
    server.shutdown()


@pytest.fixture
def day() -> Iterator[date]:
    """A day with exactly one new story, far from real content and outside every conference window (March)."""
    run = uuid.uuid4().hex[:8]
    the_day = date(2031, 3, 1 + int(run, 16) % 28)
    paper = f"g3-{run}"
    sql("insert into app.topics (key, slug, label, title) values ('mCRC-MSI-H', 'msi-h', 'MSI-H', 'MSI-H mCRC')"
        " on conflict do nothing")  # fmt: skip
    sql(
        "insert into app.papers (id, slug, topic_key, year, journal, study_type, regimen, endpoint, result, bottom_line,"
        " source, reviewed_at, detail_html) values (%s, %s, 'mCRC-MSI-H', 2026, 'NEJM', 'Phase 3 RCT', 'Drug', 'OS',"
        " 'HR 0.5', '5 年存活 58.7%%', 'fulltext', '2026-11-01', '<p>x</p>')",
        (paper, paper),
    )
    sql(
        "insert into app.news (id, paper_id, published_at, headline, dek, key, body, review_status)"
        " values (%s, %s, %s, '[\"NICHE-2 \", \"五年追蹤\"]', '術前雙免疫後 5 年存活 58.7%%', '{}',"
        ' \'[{"heading": "為什麼重要", "text": "長期追蹤結果支持術前免疫策略。"}]\', \'accepted\')',
        (f"g3-news-{run}", paper, the_day),
    )
    yield the_day
    sql("delete from app.line_broadcasts where day = %s", (the_day,))
    sql("delete from app.news where paper_id = %s", (paper,))
    sql("delete from app.papers where id = %s", (paper,))


def test_message_is_the_daily_pick_text_under_a_heading() -> None:
    from guthub_api.daily import Candidate

    pick = Candidate(
        "news",
        "x",
        "NICHE-2 五年追蹤",
        "術前雙免疫後 5 年存活 58.7%",
        "/news/x/",
        date(2026, 11, 17),
        False,
        "長期追蹤結果支持術前免疫策略。",
    )
    assert message(pick, ORIGIN) == (
        "GutHub 晨間摘要｜11 月 17 日\n\n"
        "NICHE-2 五年追蹤\n\n"
        "重點：術前雙免疫後 5 年存活 58.7%\n\n"
        "臨床意義：長期追蹤結果支持術前免疫策略。\n\n"
        "閱讀完整整理：\nhttps://guthub.tw/news/x/"
    )


def test_broadcasts_the_days_pick_once(day: date, line: tuple[str, MockLine]) -> None:
    base, mock = line
    result = broadcast_daily(API_DB_URL, day, ORIGIN, TOKEN, base)
    assert result["status"] == "sent"
    [request] = mock.requests
    assert request["path"] == "/v2/bot/message/broadcast"
    assert request["auth"] == f"Bearer {TOKEN}"
    uuid.UUID(request["key"])  # a valid retry key
    [text] = request["body"]["messages"]
    assert text["type"] == "text" and "五年追蹤" in text["text"] and "5 年存活 58.7%" in text["text"]
    # The schedule fires again, or someone reruns the job: nothing is sent.
    assert broadcast_daily(API_DB_URL, day, ORIGIN, TOKEN, base)["status"] == "already-sent"
    assert len(mock.requests) == 1


def test_during_a_conference_the_message_lists_the_day(line: tuple[str, MockLine]) -> None:
    # 2031-10-xx falls in the ESMO window: one message, every addition of the day in it (G9 #120).
    run = uuid.uuid4().hex[:8]
    the_day = date(2031, 10, 1 + int(run, 16) % 28)
    papers = [f"g9-{run}-{i}" for i in range(2)]
    sql("insert into app.topics (key, slug, label, title) values ('mCRC-MSI-H', 'msi-h', 'MSI-H', 'MSI-H mCRC')"
        " on conflict do nothing")  # fmt: skip
    try:
        for i, paper in enumerate(papers):
            sql(
                "insert into app.papers (id, slug, topic_key, year, journal, study_type, regimen, endpoint, result,"
                " bottom_line, source, reviewed_at, detail_html) values (%s, %s, 'mCRC-MSI-H', 2031, 'Lancet',"
                " 'Phase 3 RCT', %s, 'OS', 'HR 0.7', %s, 'fulltext', %s, '<p>x</p>')",
                (paper, paper, f"Drug {i}", f"結論 {i}", the_day),
            )
        base, mock = line
        assert broadcast_daily(API_DB_URL, the_day, ORIGIN, TOKEN, base)["status"] == "sent"
        [request] = mock.requests
        [text] = request["body"]["messages"]
        assert text["text"].startswith("GutHub｜ESMO Congress 期間速報")
        assert "結論 0" in text["text"] and "結論 1" in text["text"]
    finally:
        sql("delete from app.line_broadcasts where day = %s", (the_day,))
        sql("delete from app.papers where id = any(%s)", (papers,))


def test_a_failed_send_is_retried_with_the_same_key(day: date, line: tuple[str, MockLine]) -> None:
    base, mock = line
    mock.statuses = [500]
    with pytest.raises(RuntimeError):
        broadcast_daily(API_DB_URL, day, ORIGIN, TOKEN, base)
    assert sql("select sent_at from app.line_broadcasts where day = %s", (day,)) == [(None,)]
    assert broadcast_daily(API_DB_URL, day, ORIGIN, TOKEN, base)["status"] == "sent"
    assert mock.requests[0]["key"] == mock.requests[1]["key"]


def test_line_refusing_a_repeat_counts_as_sent(day: date, line: tuple[str, MockLine]) -> None:
    # LINE accepted the message but the job died before recording it: the retry gets 409 for the same key.
    base, mock = line
    sql("insert into app.line_broadcasts (day, retry_key, url) values (%s, %s, '/news/x/')", (day, uuid.uuid4()))
    key = str(sql("select retry_key from app.line_broadcasts where day = %s", (day,))[0][0])
    mock.accepted.add(key)
    assert broadcast_daily(API_DB_URL, day, ORIGIN, TOKEN, base)["status"] == "sent"
    assert mock.requests[0]["key"] == key


def test_a_day_without_new_content_sends_nothing(line: tuple[str, MockLine]) -> None:
    base, mock = line
    assert broadcast_daily(API_DB_URL, date(2001, 1, 1), ORIGIN, TOKEN, base) == {"status": "nothing-new"}
    assert mock.requests == []


def test_dry_run_prints_and_sends_nothing(day: date, line: tuple[str, MockLine]) -> None:
    base, mock = line
    result = broadcast_daily(API_DB_URL, day, ORIGIN, None, base)
    assert result["status"] == "dry-run" and "五年追蹤" in result["text"]
    assert mock.requests == [] and sql("select 1 from app.line_broadcasts where day = %s", (day,)) == []


def test_the_job_needs_a_token_unless_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUTHUB_DATABASE_URL", API_DB_URL)
    monkeypatch.delenv("GUTHUB_LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    assert maintenance.main(["line-daily"]) == 1
    assert maintenance.main(["line-daily", "--dry-run", "--date", "2001-01-01"]) == 0
