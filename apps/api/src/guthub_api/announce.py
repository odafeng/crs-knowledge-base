"""Push new stories to every subscribed browser (C5 #95). Run as a scheduled job: maintenance announce-news.

A story is announced at most once: its app.push_announcements row is claimed before anything is sent, so reruns,
page rebuilds and deploys never repeat a notification. Only stories published in the last FRESH_DAYS days qualify,
so a backlog imported later (or a job that was off for a week) does not notify anyone about old news.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

import psycopg
import requests
from pywebpush import WebPushException, webpush

logger = logging.getLogger("guthub_api.announce")

GONE = {404, 410}  # the push service says this subscription no longer exists
TTL = 24 * 3600  # a phone that stays offline longer than a day does not get yesterday's story
TIMEOUT = 10  # seconds per push service request, so one slow service cannot hold up the job
FRESH_DAYS = 2


@dataclass(frozen=True)
class Subscription:
    endpoint: str
    p256dh: str
    auth: str


type Deliver = Callable[[Subscription, str, str], None]


def payload(news_id: str, headline: list[str], dek: str) -> str:
    """What sw.js receives: the notification text and the story's path on the site."""
    return json.dumps(
        {"title": "".join(headline), "body": dek, "url": f"/news/{news_id}/", "tag": news_id}, ensure_ascii=False
    )


def web_push(private_key: str, subject: str) -> Deliver:
    def deliver(subscription: Subscription, data: str, topic: str) -> None:
        webpush(
            {"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
            data,
            vapid_private_key=private_key,
            vapid_claims={"sub": subject},  # a fresh dict each time: the library adds aud and exp to it
            ttl=TTL,
            headers={"Topic": topic},  # a second push about the same story replaces the first while still queued
            timeout=TIMEOUT,
        )

    return deliver


def _drop(conn: psycopg.Connection, subscription: Subscription) -> None:
    conn.execute("delete from app.push_subscriptions where endpoint = %s", (subscription.endpoint,))


def announce_news(url: str, deliver: Deliver) -> dict[str, int]:
    totals = {"stories": 0, "sent": 0, "removed": 0, "failed": 0}
    with psycopg.connect(url, autocommit=True) as conn:
        stories = conn.execute(
            "select n.id, n.headline, n.dek from app.public_news n"
            " where n.published_at >= current_date - %s"
            " and not exists (select 1 from app.push_announcements a where a.news_id = n.id)"
            " order by n.published_at, n.id",
            (FRESH_DAYS,),
        ).fetchall()
        for news_id, headline, dek in stories:
            claimed = conn.execute(
                "insert into app.push_announcements (news_id) values (%s) on conflict do nothing returning news_id",
                (news_id,),
            ).fetchone()
            if claimed is None:  # another run got there first
                continue
            data, topic = payload(news_id, headline, dek), news_id[:32]
            sent = removed = failed = 0
            rows = conn.execute("select endpoint, p256dh, auth from app.push_subscriptions").fetchall()
            for row in rows:
                subscription = Subscription(*row)
                try:
                    deliver(subscription, data, topic)
                    sent += 1
                except WebPushException as error:
                    # The push service answered: a gone browser is deleted; anything else may work next time.
                    if error.response is not None and error.response.status_code in GONE:
                        _drop(conn, subscription)
                        removed += 1
                    else:
                        failed += 1
                except requests.RequestException:
                    # The network to the push service failed (timeout, connection): the browser may be fine.
                    failed += 1
                except Exception:
                    # One browser must never stop the story reaching the others. This failed before any push service
                    # answered, e.g. keys that cannot encrypt, so it can never work: drop it.
                    logger.warning("Dropping a subscription that cannot be sent to", exc_info=True)
                    _drop(conn, subscription)
                    removed += 1
            conn.execute(
                "update app.push_announcements set sent = %s, removed = %s, failed = %s where news_id = %s",
                (sent, removed, failed, news_id),
            )
            totals["stories"] += 1
            totals["sent"] += sent
            totals["removed"] += removed
            totals["failed"] += failed
    return totals
