"""Forum threads in natural-language search (H8 #130, ADR-0022), against the real database with a fake embedder.

Only verified colorectal surgeons get forum results; everyone else gets the public passages alone, whatever session
they send. A hidden or deleted post leaves the results at once, before the indexer runs again.
"""

from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from guthub_api.main import API_PREFIX
from test_comments import schema, sql
from test_forum import Forum, forum, make_client, moderate, published_thread, reply  # noqa: F401
from test_semantic import literal, unit

URL = f"{API_PREFIX}/semantic-search"


@pytest.fixture
def search(forum: Forum) -> Iterator[TestClient]:  # noqa: F811
    sql("delete from app.embedding_usage")
    sql("delete from app.query_usage")
    vectors = {"lateral nodes": unit(7), "weather": unit(8)}
    for client in make_client(search_per_minute=100):
        cast("Any", client.app).state.embed = lambda text: (vectors[text], 7)
        yield client
    sql("delete from app.search_chunks where kind = 'forum'")
    sql("delete from app.embedding_usage")
    sql("delete from app.query_usage")


def index(post: str, thread: str, vector: list[float]) -> None:
    """What scripts/search_index.py stores for a forum post."""
    sql(
        "insert into app.search_chunks (kind, ref, path, title, snippet, content_hash, model, embedding)"
        " values ('forum', %s, %s, 'indexed title', 'indexed snippet', 'h', 'voyage-4', %s::extensions.vector)",
        (post, f"/forum/{thread}/", literal(vector)),
    )


def forum_hits(client: TestClient, headers: dict[str, str], query: str = "lateral nodes") -> list[dict[str, Any]]:
    response = client.post(URL, json={"query": query}, headers=headers)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store", response.text
    schema("SemanticResults").validate(response.json())
    return [r for r in response.json()["results"] if r["kind"] == "forum"]


def test_only_verified_members_get_forum_threads(search: TestClient, forum: Forum) -> None:  # noqa: F811
    f = forum
    thread = published_thread(search, f, f.surgeon, title="Lateral nodes after CRT", anonymous=True)
    index(thread, thread, unit(7))
    [hit] = forum_hits(search, f.headers(f.peer))
    # Title and snippet are read live from the visible posts, never an author.
    assert hit == {"kind": "forum", "path": f"/forum/{thread}/", "title": "Lateral nodes after CRT",
                   "snippet": "How long do you follow cCR?", "score": 1.0}  # fmt: skip
    for user in (None, f.newbie, f.member, f.admin):
        assert forum_hits(search, f.headers(user)) == []
    assert forum_hits(search, {"Authorization": "Bearer nope"}) == []  # a bad session is just a public search
    assert forum_hits(search, f.headers(f.peer), "weather") == []  # below the relevance threshold
    response = search.post(URL, json={"query": "lateral nodes"}, headers=f.headers(f.peer)).text
    assert str(f.surgeon) not in response and "王醫師" not in response


def test_a_thread_is_listed_once_and_leaves_with_its_posts(search: TestClient, forum: Forum) -> None:  # noqa: F811
    f = forum
    thread = published_thread(search, f, f.surgeon)
    answer = reply(search, f, f.surgeon, thread, "Dissect if above 7 mm.").json()["id"]
    index(thread, thread, unit(7))
    index(answer, thread, unit(7, 9))
    [hit] = forum_hits(search, f.headers(f.peer))
    assert hit["path"] == f"/forum/{thread}/" and hit["score"] == 1.0

    # Hiding the opener hides the thread and every reply in it, before any re-index.
    assert moderate(search, f, thread, "hide").status_code == 200
    assert forum_hits(search, f.headers(f.peer)) == []
    assert moderate(search, f, thread, "publish").status_code == 200
    # A deleted reply leaves at once; the thread is still found through its opener, until that is deleted too.
    index_only_reply = f"{API_PREFIX}/forum/posts/{answer}"
    assert search.delete(index_only_reply, headers=f.headers(f.surgeon)).status_code == 204
    sql("update app.search_chunks set embedding = %s::extensions.vector where ref = %s", (literal(unit(9)), thread))
    assert forum_hits(search, f.headers(f.peer)) == []  # only the deleted reply matched the question
    sql("update app.search_chunks set embedding = %s::extensions.vector where ref = %s", (literal(unit(7)), thread))
    assert [h["path"] for h in forum_hits(search, f.headers(f.peer))] == [f"/forum/{thread}/"]
    assert search.delete(f"{API_PREFIX}/forum/posts/{thread}", headers=f.headers(f.surgeon)).status_code == 204
    assert forum_hits(search, f.headers(f.peer)) == []
