"""Network utilities with retry logic."""

import json
import time
import urllib.request
from typing import Any


def fetch_with_retry(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 15,
    max_retries: int = 3,
    backoff_base: float = 1.0,
) -> bytes:
    """Fetch a URL with exponential backoff retry.

    Retries on 429, 5xx, timeout, and connection errors.
    Raises on 4xx (except 429) and after exhausting retries.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                last_error = e
            else:
                raise  # 4xx (except 429) — don't retry
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = e

        if attempt < max_retries - 1:
            delay = backoff_base * (2 ** attempt)
            time.sleep(delay)

    raise last_error  # type: ignore[misc]


def fetch_json(url: str, **kwargs: Any) -> Any:
    """Fetch URL and parse as JSON, with retry."""
    data = fetch_with_retry(url, **kwargs)
    return json.loads(data)
