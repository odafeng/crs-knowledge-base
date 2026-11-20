"""The daily comment digest email (G8 #119, ADR-0022).

Runs as the Cloud Run job comment-digest at 07:30 Taiwan time and covers comments published the previous Taiwan day.
Each reader who follows a paper that got comments from others that day gets one email: per paper, how many new
comments and a link, plus links to unfollow that paper or stop the digest. No commenter is named, signed or not, and
no comment text is quoted. Addresses come from app.comment_digest(), the one function that hands guthub_api an email,
and only for these readers.

At most one email per reader and day: the job claims (account, day) in app.comment_digests and sends with that row's
key as Resend's Idempotency-Key, so a rerun after Resend took the mail but before sent_at was recorded gets the
original answer instead of a second email. A failed send leaves the claim open for the job's retry; the job still
tries the other readers and exits non-zero, which the job-failure alert reports.
"""

import html
import json
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from guthub_api.daily import TAIPEI

RESEND_API = "https://api.resend.com"
SENDER = "GutHub <no-reply@guthub.tw>"
TIMEOUT = 30


@dataclass(frozen=True)
class Item:
    paper_id: str
    title: str
    path: str
    count: int


@dataclass
class Digest:
    account_id: UUID
    email: str
    token: UUID
    items: list[Item] = field(default_factory=list)


def gather(conn: psycopg.Connection[Any], day: date) -> list[Digest]:
    """Everyone with something to read for `day` (Taiwan time), busiest paper first."""
    since = datetime.combine(day, time(), TAIPEI)
    rows = (
        conn.cursor(row_factory=dict_row)
        .execute(
            "select d.account_id, d.email, d.digest_token, d.paper_id, d.new_comments, p.slug, p.regimen, p.journal,"
            " p.year from app.comment_digest(%s, %s) d join app.public_papers p on p.id = d.paper_id"
            " order by d.account_id, d.new_comments desc, d.paper_id",
            (since, since + timedelta(days=1)),
        )
        .fetchall()
    )
    digests: dict[UUID, Digest] = {}
    for r in rows:
        digest = digests.setdefault(r["account_id"], Digest(r["account_id"], r["email"], r["digest_token"]))
        title = f"{r['regimen']}（{r['journal']} {r['year']}）"
        digest.items.append(Item(r["paper_id"], title, f"/papers/{r['slug']}/#comments", r["new_comments"]))
    return list(digests.values())


def _links(digest: Digest, origin: str) -> tuple[str, str, list[str]]:
    base = origin.rstrip("/")
    stop = f"{base}/unsubscribe/?{urlencode({'t': str(digest.token)})}"
    unfollow = [f"{base}/unsubscribe/?{urlencode({'t': str(digest.token), 'paper': i.paper_id})}" for i in digest.items]
    return base, stop, unfollow


def render(digest: Digest, day: date, origin: str) -> dict[str, Any]:
    """Subject, plain text and HTML. Titles and counts only: never a commenter's name or a comment's words."""
    base, stop, unfollow = _links(digest, origin)
    total = sum(item.count for item in digest.items)
    subject = f"GutHub｜你追蹤的文獻有 {total} 則新留言"
    intro = f"{day.month} 月 {day.day} 日，你追蹤的 {len(digest.items)} 篇文獻有新留言："
    footer = "你會收到這封信，是因為你追蹤了這些文獻（留言過的文獻會自動追蹤）。"
    text = [intro, ""]
    for item, off in zip(digest.items, unfollow, strict=True):
        text += [f"{item.title}：{item.count} 則新留言", f"{base}{item.path}", f"取消追蹤這篇：{off}", ""]
    text += [footer, f"管理追蹤：{base}/account/", f"不再收到每日留言通知：{stop}"]
    rows = "".join(
        f'<li><a href="{html.escape(base + item.path)}">{html.escape(item.title)}</a>：{item.count} 則新留言'
        f'（<a href="{html.escape(off)}">取消追蹤這篇</a>）</li>'
        for item, off in zip(digest.items, unfollow, strict=True)
    )
    body = (
        f"<p>{html.escape(intro)}</p><ul>{rows}</ul><p>{html.escape(footer)}<br>"
        f'<a href="{html.escape(base)}/account/">管理追蹤</a>・<a href="{html.escape(stop)}">不再收到每日留言通知</a></p>'
    )
    return {
        "from": SENDER,
        "to": [digest.email],
        "subject": subject,
        "text": "\n".join(text),
        "html": body,
        "headers": {"List-Unsubscribe": f"<{stop}>"},
    }


def _send(base: str, api_key: str, key: str, payload: dict[str, Any]) -> int:
    request = urllib.request.Request(
        f"{base.rstrip('/')}/emails",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": key,
            "User-Agent": "guthub-comment-digest",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def _count(digests: Iterable[Digest]) -> int:
    return sum(len(d.items) for d in digests)


def send_digests(url: str, day: date, origin: str, api_key: str | None, base: str = RESEND_API) -> dict[str, Any]:
    """Send `day`'s digests. Without a key it is a dry run that sends and records nothing; it reports counts and the
    first message's text, never an address."""
    with psycopg.connect(url, autocommit=True) as conn:
        cur = conn.cursor(row_factory=dict_row)
        digests = gather(conn, day)
        if api_key is None:
            # The preview goes to the job log, so it carries a blank token instead of the reader's.
            blank = [Digest(d.account_id, d.email, UUID(int=0), d.items) for d in digests[:1]]
            preview = render(blank[0], day, origin)["text"] if blank else None
            return {"status": "dry-run", "readers": len(digests), "papers": _count(digests), "preview": preview}
        sent = already = failed = 0
        for digest in digests:
            cur.execute(
                "insert into app.comment_digests (account_id, day) values (%s, %s) on conflict do nothing",
                (digest.account_id, day),
            )
            claim = cur.execute(
                "select idempotency_key, sent_at from app.comment_digests where account_id = %s and day = %s",
                (digest.account_id, day),
            ).fetchone()
            assert claim is not None
            if claim["sent_at"] is not None:
                already += 1
                continue
            status = _send(base, api_key, f"comment-digest/{claim['idempotency_key']}", render(digest, day, origin))
            if status != 200:
                failed += 1
                continue
            cur.execute(
                "update app.comment_digests set sent_at = now() where account_id = %s and day = %s",
                (digest.account_id, day),
            )
            sent += 1
        return {"status": "sent" if not failed else "failed", "sent": sent, "alreadySent": already, "failed": failed}
