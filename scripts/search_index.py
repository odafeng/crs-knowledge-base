"""Embed the public content for natural-language search (H3 #125, ADR-0022).

python scripts/search_index.py --database-url URL [--dry-run]

One passage per paper, news story and treatment card, built from what the site shows, and one per published forum
post (H8 #130): the thread title and the post body, never the author, anonymous or not. Only items whose text changed
since the last run are sent to Voyage AI (VOYAGE_API_KEY); items that left the public views are removed. Tokens are
added to app.embedding_usage for the month, and the run stops before a batch once the month's cap is reached, so the
search API and this job share one budget. Runs as the content owner, after every content import or publish.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from typing import Any
from zoneinfo import ZoneInfo

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
MODEL = "voyage-4"
DIMENSIONS = 1024
BATCH = 32
MONTHLY_TOKENS = 80_000_000  # USD 5 at USD 0.06 per million tokens (ADR-0022, H2)
TAIPEI = ZoneInfo("Asia/Taipei")
MAX_CHARS = 8000  # a paper's detail page can be long; the summary fields come first and always fit

type Embed = Callable[[list[str], str], tuple[list[list[float]], int]]


@dataclass(frozen=True)
class Item:
    kind: str
    ref: str
    path: str
    title: str
    snippet: str
    text: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(f"{MODEL}\n{self.title}\n{self.text}".encode()).hexdigest()


def plain(html: str) -> str:
    text = re.sub(r"<br\s*/?>|</(?:p|li|tr|h3|div)>", "\n", html, flags=re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", text)).strip()


def items(
    papers: Iterable[dict], news: Iterable[dict], topics: Iterable[dict], forum: Iterable[dict] = ()
) -> list[Item]:
    labels = {t["key"]: t["label"] for t in topics}
    found: list[Item] = []
    for p in papers:
        title = f"{unescape(p['regimen'])}（{unescape(p['journal'])} {p['year']}）"
        summary = [title, labels.get(p["topic_key"], ""), p["study_type"], unescape(p["endpoint"]),
                   unescape(p["result"]), unescape(p["bottom_line"])]  # fmt: skip
        text = "\n".join([*summary, plain(p["detail_html"])])[:MAX_CHARS]
        found.append(Item("paper", p["id"], f"/papers/{p['slug']}/", title, unescape(p["bottom_line"]), text))
    for n in news:
        title = "".join(n["headline"])
        body = [section.get("text", "") for section in n["body"]]
        found.append(Item("news", n["id"], f"/news/{n['id']}/", title, n["dek"], "\n".join([title, n["dek"], *body])))
    for t in topics:
        for index, card in enumerate(t["standard_of_care"]):
            title = f"{t['label']}：{card['title']}"
            body = plain(card["body_html"])
            notes = [note for row in card.get("regulatory") or [] for note in
                     (row.get("regimen"), row.get("tfdaNote"), row.get("nhiNote")) if note]  # fmt: skip
            found.append(
                Item(
                    "card",
                    f"{t['key']}#{index}",
                    f"/mcrc/{t['slug']}/",
                    title,
                    body[:160],
                    "\n".join([title, body, *notes]),
                )
            )
        # Robotic surgery keeps its evidence as cards inside sections (/robotic/<section>/), not treatment cards.
        for section in t.get("robotic_sections") or []:
            for index, card in enumerate(section.get("cards", [])):
                title = f"機器手臂手術：{plain(card['title'])}"
                body = plain(card["body"])
                found.append(
                    Item("card", f"{t['key']}/{section['slug']}#{index}", f"/robotic/{section['slug']}/", title,
                         body[:160], "\n".join([title, card.get("tag", ""), body]))
                )  # fmt: skip
    # Members only: the API returns these to verified members alone. A reply carries its thread's title for context.
    for post in forum:
        found.append(
            Item("forum", str(post["id"]), f"/forum/{post['thread']}/", post["title"], post["body"][:160],
                 "\n".join([post["title"], post["body"]]))
        )  # fmt: skip
    return found


def voyage(key: str) -> Embed:
    def embed(texts: list[str], input_type: str) -> tuple[list[list[float]], int]:
        body = {"input": texts, "model": MODEL, "input_type": input_type, "output_dimension": DIMENSIONS}
        request = urllib.request.Request(
            VOYAGE_URL,
            json.dumps(body).encode(),
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    data = json.load(response)
                break
            except urllib.error.HTTPError as error:
                if (error.code != 429 and error.code < 500) or attempt == 2:
                    raise
                time.sleep(10 * (attempt + 1))
        vectors = [row["embedding"] for row in sorted(data["data"], key=lambda row: row["index"])]
        return vectors, int(data["usage"]["total_tokens"])

    return embed


def month() -> str:
    return datetime.now(TAIPEI).date().replace(day=1).isoformat()


def used(conn: Any) -> int:
    row = conn.execute("select tokens from app.embedding_usage where month = %s", (month(),)).fetchone()
    return int(row[0]) if row else 0


def add_usage(conn: Any, tokens: int) -> None:
    conn.execute(
        "insert into app.embedding_usage (month, tokens) values (%s, %s)"
        " on conflict (month) do update set tokens = app.embedding_usage.tokens + excluded.tokens",
        (month(), tokens),
    )


def vector(values: list[float]) -> str:
    return "[" + ",".join(repr(v) for v in values) + "]"


def load(conn: Any) -> list[Item]:
    def rows(sql: str) -> list[dict]:
        cursor = conn.execute(sql)
        names = [c.name for c in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    return items(
        rows(
            "select id, slug, topic_key, year, journal, study_type, regimen, endpoint, result, bottom_line,"
            " detail_html from app.public_papers order by id"
        ),
        rows("select id, headline, dek, body from app.public_news order by id"),
        rows("select key, slug, label, standard_of_care, robotic_sections from app.topics order by key"),
        rows(
            "select v.id, coalesce(v.thread_id, v.id) as thread, coalesce(v.title, t.title) as title, v.body"
            " from app.visible_forum_posts v left join app.forum_posts t on t.id = v.thread_id order by v.id"
        ),
    )


def run(conn: Any, embed: Embed, dry_run: bool = False, cap: int = MONTHLY_TOKENS) -> dict[str, int]:
    current = load(conn)
    known = dict(((k, r), h) for k, r, h in conn.execute("select kind, ref, content_hash from app.search_chunks"))
    stale = [item for item in current if known.get((item.kind, item.ref)) != item.digest]
    gone = set(known) - {(item.kind, item.ref) for item in current}
    report = {"items": len(current), "embedded": 0, "removed": len(gone), "tokens": 0}
    if dry_run:
        return {**report, "embedded": len(stale)}
    for kind, ref in gone:
        conn.execute("delete from app.search_chunks where kind = %s and ref = %s", (kind, ref))
    for start in range(0, len(stale), BATCH):
        if used(conn) >= cap:
            raise RuntimeError(f"monthly embedding cap of {cap} tokens reached; {len(stale) - start} items left")
        batch = stale[start : start + BATCH]
        vectors, tokens = embed([item.text for item in batch], "document")
        add_usage(conn, tokens)
        for item, values in zip(batch, vectors, strict=True):
            conn.execute(
                "insert into app.search_chunks (kind, ref, path, title, snippet, content_hash, model, embedding)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s::extensions.vector) on conflict (kind, ref) do update set"
                " path = excluded.path, title = excluded.title, snippet = excluded.snippet,"
                " content_hash = excluded.content_hash, model = excluded.model, embedding = excluded.embedding,"
                " indexed_at = now()",
                (item.kind, item.ref, item.path, item.title, item.snippet, item.digest, MODEL, vector(values)),
            )
        report["embedded"] += len(batch)
        report["tokens"] += tokens
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=os.environ.get("GUTHUB_CONTENT_DATABASE_URL"))
    parser.add_argument("--dry-run", action="store_true", help="count what would be embedded, call nothing")
    args = parser.parse_args(argv)
    key = os.environ.get("VOYAGE_API_KEY")
    if not args.database_url or not (key or args.dry_run):
        parser.error("--database-url (or GUTHUB_CONTENT_DATABASE_URL) and VOYAGE_API_KEY are required")
    import psycopg

    with psycopg.connect(args.database_url, autocommit=True) as conn:
        report = run(conn, voyage(key or ""), args.dry_run)
    print(json.dumps({"job": "search-index", **report}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
