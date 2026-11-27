"""ChatGPT News Radar GitHub Intake Adapter (N1 #286, ADR-0031).

One-way, read-only GitHub REST API intake for candidate batches emitted by external
producers (such as ChatGPT News Radar) into a dedicated inbox repository.

Security invariants (fail closed):
- Extracts exactly ONE fenced ```json ... ``` block per issue body.
- Enforces MAX_PAYLOAD_BYTES (64 KiB) before JSON decoding.
- Rejects duplicate JSON object keys via object_pairs_hook.
- Validates v1.0 (legacy PoC like #280) and v1.1 (with taxonomy_version + domain hints).
- If test_mode is not strictly False OR publish_allowed is not strictly True, isolates
  the batch into app.news_ingest_batches (status='isolated_test') and writes ZERO rows
  to app.news_candidates or app.news_events.
- Keyed idempotently by (producer, batch_id):
  - Same payload_hash -> idempotent no-op.
  - Changed payload_hash (issue edited post-ingest) -> conflict isolation; never overwrites.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from taxonomy_registry import TaxonomyError, TaxonomyRegistry, load_registry  # noqa: E402

MAX_PAYLOAD_BYTES = 64 * 1024
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})
VALID_EVENT_TYPES = frozenset({"regulatory", "guideline", "trial", "society", "device", "safety", "clinical"})
_FENCED_JSON_RE = re.compile(r"```json[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL | re.IGNORECASE)
_HTTPS_URL_RE = re.compile(r"^https://[^\s<>\"']+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class IntakeValidationError(ValueError):
    """Raised when an intake issue body violates schema, size, or duplicate-key rules."""


@dataclass(frozen=True)
class ParsedBatch:
    schema_version: str
    producer: str
    batch_id: str
    test_mode: bool
    publish_allowed: bool
    taxonomy_version: str | None
    payload_hash: str
    items: tuple[dict[str, Any], ...]
    raw_payload: dict[str, Any]

    @property
    def is_isolated_test(self) -> bool:
        """Fail closed: only test_mode==False AND publish_allowed==True may enter candidates."""
        return (self.test_mode is not False) or (self.publish_allowed is not True)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise IntakeValidationError(f"duplicate JSON key: {key!r}")
        out[key] = value
    return out


def extract_single_json_block(body: str) -> str:
    """Extract the sole fenced ```json ... ``` block from an issue body; reject 0 or >1 blocks."""
    if not isinstance(body, str) or not body.strip():
        raise IntakeValidationError("issue body is empty")
    matches = _FENCED_JSON_RE.findall(body)
    if len(matches) == 0:
        raise IntakeValidationError("issue body contains no fenced ```json block")
    if len(matches) > 1:
        raise IntakeValidationError(f"issue body contains {len(matches)} fenced ```json blocks; exactly 1 required")
    block = matches[0].strip()
    if len(block.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise IntakeValidationError(f"JSON payload exceeds {MAX_PAYLOAD_BYTES} bytes limit")
    return block


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_optional_date(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise IntakeValidationError(f"{field} must be YYYY-MM-DD, got {value!r}")
    return value


def _normalize_item(raw_item: Any, index: int, *, schema_version: str) -> dict[str, Any]:
    if not isinstance(raw_item, dict):
        raise IntakeValidationError(f"items[{index}] must be an object")
    title = str(raw_item.get("title") or "").strip()
    url = str(raw_item.get("canonical_url") or raw_item.get("url") or "").strip()
    if not title:
        raise IntakeValidationError(f"items[{index}] missing non-empty title")
    if not _HTTPS_URL_RE.match(url):
        raise IntakeValidationError(f"items[{index}] canonical_url/url must be https://, got {url!r}")
    event_type = str(raw_item.get("event_type") or raw_item.get("category") or "clinical").strip().lower()
    if event_type not in VALID_EVENT_TYPES:
        raise IntakeValidationError(f"items[{index}] unsupported event_type {event_type!r}")

    primary_hint = raw_item.get("primary_domain_hint")
    if primary_hint is not None and not isinstance(primary_hint, str):
        raise IntakeValidationError(f"items[{index}] primary_domain_hint must be a string or null")
    secondary_hints = raw_item.get("secondary_domain_hints") or []
    if not isinstance(secondary_hints, list) or not all(isinstance(x, str) for x in secondary_hints):
        raise IntakeValidationError(f"items[{index}] secondary_domain_hints must be a list of strings")

    external_id = str(raw_item.get("external_id") or raw_item.get("id") or "").strip() or None
    published_at = _validate_optional_date(raw_item.get("published_at"), f"items[{index}].published_at")
    event_date = _validate_optional_date(raw_item.get("event_date"), f"items[{index}].event_date")
    effective_date = _validate_optional_date(raw_item.get("effective_date"), f"items[{index}].effective_date")

    dedup_basis = external_id or f"{url}|{event_type}|{published_at or event_date or ''}"
    dedup_key = f"intake:{hashlib.sha256(dedup_basis.encode('utf-8')).hexdigest()[:32]}"

    return {
        "external_id": external_id,
        "dedup_key": dedup_key,
        "canonical_url": url,
        "title": title,
        "event_type": event_type,
        "published_at": published_at,
        "event_date": event_date,
        "effective_date": effective_date,
        "primary_domain_hint": primary_hint.strip() if isinstance(primary_hint, str) and primary_hint.strip() else None,
        "secondary_domain_hints": [h.strip() for h in secondary_hints if h.strip()],
        "raw_metadata": {
            "schema_version": schema_version,
            **{k: v for k, v in raw_item.items() if k not in ("verified_source_text",)},
        },
    }


def parse_intake_body(body: str, registry: TaxonomyRegistry | None = None) -> ParsedBatch:
    """Strictly parse and validate an intake issue body into a ParsedBatch."""
    block = extract_single_json_block(body)
    try:
        payload = json.loads(block, object_pairs_hook=_no_duplicate_keys)
    except IntakeValidationError:
        raise
    except json.JSONDecodeError as exc:
        raise IntakeValidationError(f"invalid JSON payload: {exc}") from exc

    if not isinstance(payload, dict):
        raise IntakeValidationError("JSON payload root must be an object")

    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, str) or schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise IntakeValidationError(f"unsupported schema_version: {schema_version!r}")

    producer = payload.get("producer")
    batch_id = payload.get("batch_id")
    if not isinstance(producer, str) or not producer.strip():
        raise IntakeValidationError("missing non-empty string 'producer'")
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise IntakeValidationError("missing non-empty string 'batch_id'")

    test_mode = payload.get("test_mode")
    publish_allowed = payload.get("publish_allowed")
    if not isinstance(test_mode, bool):
        raise IntakeValidationError("test_mode must be a boolean")
    if not isinstance(publish_allowed, bool):
        raise IntakeValidationError("publish_allowed must be a boolean")

    taxonomy_version: str | None = None
    if schema_version == "1.1":
        raw_tv = payload.get("taxonomy_version")
        if not isinstance(raw_tv, str) or not raw_tv.strip():
            raise IntakeValidationError("schema v1.1 requires taxonomy_version")
        reg = registry or load_registry()
        try:
            reg.require_version(raw_tv)
        except TaxonomyError as exc:
            raise IntakeValidationError(str(exc)) from exc
        taxonomy_version = raw_tv

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise IntakeValidationError("items must be a list")

    items = tuple(_normalize_item(it, idx, schema_version=schema_version) for idx, it in enumerate(raw_items))
    return ParsedBatch(
        schema_version=schema_version,
        producer=producer.strip(),
        batch_id=batch_id.strip(),
        test_mode=test_mode,
        publish_allowed=publish_allowed,
        taxonomy_version=taxonomy_version,
        payload_hash=canonical_payload_hash(payload),
        items=items,
        raw_payload=payload,
    )


def ingest_batch(
    conn: Any,
    batch: ParsedBatch,
    *,
    source_repo: str | None = None,
    source_issue_number: int | None = None,
    source_author: str | None = None,
) -> dict[str, Any]:
    """Persist one validated batch idempotently with fail-closed test isolation and hash-conflict detection."""
    from psycopg.types.json import Jsonb

    with conn.transaction(), conn.cursor() as cur:
        existing = cur.execute(
            "select id, payload_hash, status from app.news_ingest_batches"
            " where producer = %s and batch_id = %s for update",
            (batch.producer, batch.batch_id),
        ).fetchone()
        if existing is not None:
            existing_id, existing_hash, existing_status = existing[0], existing[1], existing[2]
            if existing_hash == batch.payload_hash:
                return {
                    "outcome": "duplicate_noop",
                    "batch_uuid": str(existing_id),
                    "status": existing_status,
                    "candidates_inserted": 0,
                }
            cur.execute(
                "update app.news_ingest_batches"
                " set status = 'conflict', error_detail = %s, updated_at = now()"
                " where id = %s",
                (
                    f"payload_hash mismatch on re-ingest: expected {existing_hash}, got {batch.payload_hash}",
                    existing_id,
                ),
            )
            return {
                "outcome": "conflict",
                "batch_uuid": str(existing_id),
                "status": "conflict",
                "candidates_inserted": 0,
            }

        status = "isolated_test" if batch.is_isolated_test else "ingested"
        row = cur.execute(
            "insert into app.news_ingest_batches"
            " (producer, batch_id, schema_version, source_repo, source_issue_number, source_author,"
            "  payload_hash, test_mode, publish_allowed, status, item_count, raw_payload)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " returning id",
            (
                batch.producer,
                batch.batch_id,
                batch.schema_version,
                source_repo,
                source_issue_number,
                source_author,
                batch.payload_hash,
                batch.test_mode,
                batch.publish_allowed,
                status,
                len(batch.items),
                Jsonb(batch.raw_payload),
            ),
        ).fetchone()
        assert row is not None
        batch_uuid = row[0]

        inserted = 0
        if status == "ingested":
            for item in batch.items:
                cur.execute(
                    "insert into app.news_candidates"
                    " (batch_id, external_id, dedup_key, canonical_url, title, event_type,"
                    "  published_at, event_date, effective_date, primary_domain_hint,"
                    "  secondary_domain_hints, raw_metadata)"
                    " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    " on conflict (dedup_key) do nothing",
                    (
                        batch_uuid,
                        item["external_id"],
                        item["dedup_key"],
                        item["canonical_url"],
                        item["title"],
                        item["event_type"],
                        item["published_at"],
                        item["event_date"],
                        item["effective_date"],
                        item["primary_domain_hint"],
                        item["secondary_domain_hints"],
                        Jsonb(item["raw_metadata"]),
                    ),
                )
                inserted += cur.rowcount

        return {
            "outcome": status,
            "batch_uuid": str(batch_uuid),
            "status": status,
            "candidates_inserted": inserted,
        }


def poll_inbox_issues(
    repo: str,
    *,
    token: str | None = None,
    label: str | None = None,
    state: str = "open",
    api_base: str = "https://api.github.com",
    per_page: int = 100,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    """One-way read-only paginated GitHub REST poll for an isolated news-inbox repository."""
    if "/" not in repo:
        raise ValueError(f"repo must be 'owner/name', got {repo!r}")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "guthub-newsroom-intake",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    collected: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        params: dict[str, Any] = {"state": state, "per_page": per_page, "page": page}
        if label:
            params["labels"] = label
        url = f"{api_base.rstrip('/')}/repos/{repo}/issues?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=20) as resp:
            batch = json.loads(resp.read().decode("utf-8"))
        if not isinstance(batch, list) or not batch:
            break
        collected.extend(issue for issue in batch if isinstance(issue, dict) and "pull_request" not in issue)
        if len(batch) < per_page:
            break
    return collected
