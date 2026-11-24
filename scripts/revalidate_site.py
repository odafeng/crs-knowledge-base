"""Trigger Next.js on-demand cache revalidation after database writes (K3 #253).

Reads GUTHUB_REVALIDATE_URL (e.g. https://guthub.tw/api/revalidate) and GUTHUB_REVALIDATE_SECRET from the
environment. A missing config or transient network failure is logged and never fails the caller, since the
1-hour ISR TTL remains as a fallback.
"""

import json
import os
import sys
import urllib.request

URL_ENV = "GUTHUB_REVALIDATE_URL"
SECRET_ENV = "GUTHUB_REVALIDATE_SECRET"
DEFAULT_TAGS = ["guthub-content"]
TIMEOUT = 10


def revalidate_site(
    tags: list[str] | None = None,
    paths: list[str] | None = None,
    *,
    url: str | None = None,
    secret: str | None = None,
) -> bool:
    """POST a revalidation request to Next.js. Returns True on HTTP 2xx, False otherwise."""
    target = (url if url is not None else os.environ.get(URL_ENV, "")).strip()
    token = (secret if secret is not None else os.environ.get(SECRET_ENV, "")).strip()
    if not target or not token:
        return False
    # Next.js sets trailingSlash: true and answers 308 on POST without a trailing slash, which urllib does not follow.
    if "?" not in target and not target.endswith("/"):
        target += "/"

    payload: dict[str, list[str]] = {"tags": tags if tags is not None else DEFAULT_TAGS}
    if paths:
        payload["paths"] = paths

    req = urllib.request.Request(
        target,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if 200 <= resp.status < 300:
                print(f"  [Revalidate] OK ({resp.status})")
                return True
            print(f"  [Revalidate] unexpected status: {resp.status}", file=sys.stderr)
            return False
    except Exception as exc:
        print(f"  [Revalidate] skipped/failed: {exc}", file=sys.stderr)
        return False
