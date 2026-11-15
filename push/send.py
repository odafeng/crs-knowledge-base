"""Send a push notification for one news story to every subscriber.

    python -m push.send --news data/news.json --id niche2-five-year

Environment: PUSH_API, PUSH_SERVICE_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT (a mailto: or https: contact
the push services can reach if something goes wrong).
"""

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

from pywebpush import WebPushException, webpush

from .store import Store, Subscription

GONE = {404, 410}  # the push service says this subscription no longer exists
TTL = 24 * 3600  # a phone that stays offline longer than a day does not get yesterday's story


@dataclass(frozen=True)
class Outcome:
    sent: int
    removed: int
    failed: int


def payload(story: dict) -> str:
    """What sw.js receives. `url` is relative to the site root, so it works under any base path."""
    return json.dumps(
        {"title": "".join(story["headline"]), "body": story["dek"], "url": f"news/{story['id']}/", "tag": story["id"]},
        ensure_ascii=False,
    )


def _deliver(subscription: Subscription, data: str, topic: str, private_key: str, subject: str) -> None:
    webpush(
        {"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
        data,
        vapid_private_key=private_key,
        vapid_claims={"sub": subject},  # a fresh dict each time: the library adds aud and exp to it
        ttl=TTL,
        headers={"Topic": topic},  # a second push about the same story replaces the first while it is still queued
    )


def send(story: dict, store: Store, private_key: str, subject: str) -> Outcome:
    data, topic = payload(story), story["id"][:32]
    sent = removed = failed = 0
    for subscription in store.subscriptions():
        try:
            _deliver(subscription, data, topic, private_key, subject)
            sent += 1
        except WebPushException as error:
            # One dead or failing subscription must not stop the rest; a gone one is deleted so it is not retried.
            if error.response is not None and error.response.status_code in GONE:
                store.remove(subscription.endpoint)
                removed += 1
            else:
                failed += 1
    return Outcome(sent, removed, failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--news", type=Path, required=True)
    parser.add_argument("--id", required=True, help="id of the story to announce")
    args = parser.parse_args()
    story = next(s for s in json.loads(args.news.read_text(encoding="utf-8")) if s["id"] == args.id)
    store = Store(os.environ["PUSH_API"], os.environ["PUSH_SERVICE_KEY"])
    print(send(story, store, os.environ["VAPID_PRIVATE_KEY"], os.environ["VAPID_SUBJECT"]))
