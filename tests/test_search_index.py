"""Search index (H3 #125): passages built from the public content, re-embedded only when they change."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_content import apply

import search_index as si
from test_import_content import conn, needs_db, rows  # noqa: F401

PAPER = {"id": "fresco", "slug": "fresco", "topic_key": "generic-CRS", "year": 2018, "journal": "JAMA",
         "study_type": "Phase 3 RCT", "regimen": "Fruquintinib &amp; BSC", "endpoint": "OS",
         "result": "HR 0.65, p&lt;.001", "bottom_line": "延長 OS", "detail_html": "<p>中國族群</p>"}  # fmt: skip
TOPICS = [
    {"key": "generic-CRS", "slug": "later-line", "label": "後線治療", "standard_of_care": [], "robotic_sections": []},
    {"key": "mCRC-MSI-H", "slug": "msi-h", "label": "MSI-H / dMMR", "robotic_sections": [],
     "standard_of_care": [{"title": "一線", "body_html": "<table><tr><td>Pembrolizumab</td></tr></table>",
                           "regulatory": [{"regimen": "Pembrolizumab", "nhiNote": "給付規定 9.69"}]}]},
    {"key": "robotic-surgery", "slug": "robotic", "label": "機器手臂手術", "standard_of_care": [],
     "robotic_sections": [{"slug": "tme", "cards": [{"tag": "ROLARR", "title": "ROLARR 試驗", "body": "<p>轉換率</p>"}]}]},
]  # fmt: skip
NEWS = {"id": "niche2", "headline": ["NICHE-2：", "五年無復發"], "dek": "術前雙免疫", "body": [{"text": "111 例"}]}


def test_passages_follow_what_the_site_shows() -> None:
    paper, news, card, robotic = si.items(
        [PAPER],
        [NEWS],
        TOPICS,
        paper_domains={"fresco": ["大腸直腸腫瘤", "Colorectal Oncology"]},
    )
    assert (paper.path, paper.title, paper.snippet) == ("/papers/fresco/", "Fruquintinib & BSC（JAMA 2018）", "延長 OS")
    assert "p<.001" in paper.text and "後線治療" in paper.text and "中國族群" in paper.text
    assert "大腸直腸腫瘤" in paper.text and "Colorectal Oncology" in paper.text
    assert (news.path, news.title, news.snippet) == ("/news/niche2/", "NICHE-2：五年無復發", "術前雙免疫")
    assert (card.ref, card.path, card.title) == ("mCRC-MSI-H#0", "/mcrc/msi-h/", "MSI-H / dMMR：一線")
    assert "給付規定 9.69" in card.text and "<" not in card.snippet
    assert (robotic.ref, robotic.path) == ("robotic-surgery/tme#0", "/robotic/tme/")


def test_the_digest_changes_with_the_text_and_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    before = si.items([PAPER], [], TOPICS[:1])[0].digest
    edited = si.items([{**PAPER, "bottom_line": "延長 OS 2.7 個月"}], [], TOPICS[:1])[0].digest
    monkeypatch.setattr(si, "MODEL", "voyage-5")
    assert len({before, edited, si.items([PAPER], [], TOPICS[:1])[0].digest}) == 3


class FakeVoyage:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def __call__(self, texts: list[str], input_type: str) -> tuple[list[list[float]], int]:
        assert input_type == "document"
        self.texts += texts
        return [[1.0] + [0.0] * (si.DIMENSIONS - 1) for _ in texts], 10 * len(texts)


@needs_db
def test_only_changed_items_are_embedded_and_withdrawn_ones_removed(conn, rows) -> None:  # noqa: F811
    apply(conn, rows)
    conn.execute("truncate app.search_chunks")
    conn.execute("delete from app.embedding_usage")
    embed = FakeVoyage()
    first = si.run(conn, embed)
    assert first["embedded"] == first["items"] > 60 and first["tokens"] == 10 * first["items"]
    assert si.used(conn) == first["tokens"]
    assert si.run(conn, embed) == {"items": first["items"], "embedded": 0, "removed": 0, "tokens": 0}
    # A paper without a story, so only its own passage leaves the public views.
    paper = conn.execute(
        "select id from app.papers where id not in (select paper_id from app.news) order by id limit 1"
    ).fetchone()[0]
    conn.execute("update app.papers set withdrawn_at = now() where id = %s", (paper,))
    assert si.run(conn, embed)["removed"] == 1
    assert conn.execute("select 1 from app.search_chunks where ref = %s", (paper,)).fetchone() is None


@needs_db
def test_the_monthly_cap_stops_before_sending_more(conn, rows) -> None:  # noqa: F811
    apply(conn, rows)
    conn.execute("truncate app.search_chunks")
    conn.execute("delete from app.embedding_usage")
    si.add_usage(conn, 100)
    embed = FakeVoyage()
    with pytest.raises(RuntimeError, match="cap"):
        si.run(conn, embed, cap=100)
    assert embed.texts == []


# --- forum posts (H8 #130) -----------------------------------------------------------------------------------------

OPENER = {"id": "11111111-1111-1111-1111-111111111111", "thread": "11111111-1111-1111-1111-111111111111",
          "title": "側方淋巴結", "body": "化放療後還在的側方淋巴結，你們會清嗎？"}  # fmt: skip
REPLY = {"id": "22222222-2222-2222-2222-222222222222", "thread": OPENER["id"], "title": "側方淋巴結",
         "body": "大於 7 mm 會清。"}  # fmt: skip


def test_forum_posts_carry_their_thread_and_no_author() -> None:
    opener, reply = si.items([], [], [], [OPENER, REPLY])
    assert (opener.kind, opener.ref, opener.path, opener.title) == ("forum", OPENER["id"], f"/forum/{OPENER['id']}/",
                                                                  "側方淋巴結")  # fmt: skip
    assert reply.path == opener.path and reply.text == "側方淋巴結\n大於 7 mm 會清。"
    assert reply.snippet == "大於 7 mm 會清。"


@needs_db
def test_published_forum_posts_are_indexed_and_hidden_ones_removed(conn, rows) -> None:  # noqa: F811
    apply(conn, rows)
    conn.execute("truncate app.search_chunks")
    author = conn.execute(
        "insert into auth.users (id, email) values (gen_random_uuid(), 'h8-index@example.test') returning id"
    ).fetchone()[0]
    conn.execute("insert into app.accounts (id, display_name, surgeon_since) values (%s, '王醫師', now())", (author,))

    def post(**fields) -> str:
        columns = {"author_id": author, "anonymous": True, **fields}
        names = ", ".join(columns)
        marks = ", ".join(["%s"] * len(columns))
        return str(conn.execute(f"insert into app.forum_posts ({names}) values ({marks}) returning id",
                                list(columns.values())).fetchone()[0])  # fmt: skip

    thread = post(title="側方淋巴結", body="化放療後還在的側方淋巴結，你們會清嗎？")
    conn.execute("update app.forum_posts set status = 'published' where id = %s", (thread,))  # the maintainer
    answer = post(thread_id=thread, body="大於 7 mm 會清。")  # trusted now: published at once
    waiting = post(title="Still pending", body="x")
    conn.execute("update app.forum_posts set status = 'pending' where id = %s", (waiting,))
    embed = FakeVoyage()
    si.run(conn, embed)
    indexed = dict(conn.execute("select ref, path from app.search_chunks where kind = 'forum'").fetchall())
    assert indexed == {thread: f"/forum/{thread}/", answer: f"/forum/{thread}/"}
    assert not any("王醫師" in text for text in embed.texts)

    conn.execute("update app.forum_posts set status = 'hidden' where id = %s", (thread,))
    assert si.run(conn, embed)["removed"] == 2  # the thread takes its replies with it
