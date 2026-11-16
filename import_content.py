"""Copy the JSON knowledge base into the PostgreSQL `app` schema (B4 #61).

data/*.json and docs/ stay authoritative until cutover (ADR-0016): this is a one-way copy and never writes back.
The whole import runs in one transaction. Re-running converges on the same rows; papers and news that left the
source are marked withdrawn instead of deleted, because reader comments may reference them.

python import_content.py --dry-run                              # build rows and manifest, no database
python import_content.py --database-url URL --dry-run           # run in a transaction, report, roll back
python import_content.py --database-url URL --manifest out.json # apply

URL may come from GUTHUB_IMPORT_DATABASE_URL instead. It needs a role that owns the app tables; guthub_api cannot
write content.
"""

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, LiteralString

from sitegen.config import ROBOTIC_KEY, TOPICS
from sitegen.load import load_kb

ROOT = Path(__file__).resolve().parent
ROBOTIC_TOPIC = {"key": ROBOTIC_KEY, "slug": "robotic", "label": "機器手臂手術", "title": "機器手臂手術"}

# Columns per table, in insert order. JSON columns are wrapped as jsonb when written.
COLUMNS: dict[str, tuple[str, ...]] = {
    "topics": ("key", "slug", "label", "title", "standard_of_care", "soc_title", "robotic_sections", "metrics"),
    "papers": (
        "id",
        "slug",
        "topic_key",
        "year",
        "journal",
        "study_type",
        "n",
        "regimen",
        "endpoint",
        "result",
        "bottom_line",
        "doi",
        "source",
        "reviewed_at",
        "review_status",
        "review_published_at",
        "detail_html",
        "source_file",
    ),  # fmt: skip
    "paper_relations": ("paper_id", "target_id", "type"),
    "research_commentary": (
        "paper_id",
        "doi",
        "pmid",
        "title",
        "journal",
        "year",
        "type",
        "summary",
        "critique",
        "new_data",
        "added_at",
        "review_status",
        "review_published_at",
    ),  # fmt: skip
    "news": (
        "id",
        "paper_id",
        "published_at",
        "headline",
        "dek",
        "key",
        "figures",
        "figure_note",
        "body",
        "review_status",
        "review_published_at",
    ),  # fmt: skip
}
# Per table: news.key is jsonb but topics.key is the text primary key, so one global set would corrupt topic keys.
JSON_COLUMNS: dict[str, set[str]] = {
    "topics": {"standard_of_care", "robotic_sections", "metrics"},
    "papers": {"n"},
    "paper_relations": set(),
    "research_commentary": set(),
    "news": {"headline", "key", "figures", "body"},
}
PRIMARY_KEYS: dict[str, LiteralString] = {"topics": "key", "papers": "id", "news": "id"}


@dataclass
class Rows:
    tables: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {name: [] for name in COLUMNS})
    sources: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _review(item: dict) -> tuple[str | None, str | None]:
    review = item.get("review") or {}
    published = review.get("publishedAt")
    return review.get("status"), published[:10] if published else None


def build_rows(root: Path = ROOT) -> Rows:
    """Map the knowledge base onto table rows. Problems are collected in `errors` instead of raised."""
    rows = Rows()
    papers_path, news_path = root / "data/papers.json", root / "data/news.json"
    raw = json.loads(papers_path.read_text(encoding="utf-8"))
    news = json.loads(news_path.read_text(encoding="utf-8"))
    rows.sources = {
        "data/papers.json": _sha256(papers_path.read_bytes()),
        "data/news.json": _sha256(news_path.read_bytes()),
    }
    try:
        kb = load_kb(papers_path, news_path)
    except (KeyError, ValueError) as exc:
        rows.errors.append(f"knowledge base does not load: {exc}")
        return rows
    loaded = {p.id: p for p in kb.papers}

    known = {t.key for t in TOPICS} | {ROBOTIC_KEY}
    rows.errors += [f"unknown topic in papers.json: {key}" for key in raw if key not in known]
    if raw.get(ROBOTIC_KEY, {}).get("papers"):
        rows.errors.append(f"{ROBOTIC_KEY} papers are not loaded by the site and cannot be imported")

    for topic in TOPICS:
        block = raw[topic.key]
        soc = block.get("standard_of_care") or {}
        rows.tables["topics"].append(
            {
                "key": topic.key,
                "slug": topic.slug,
                "label": topic.label,
                "title": topic.title,
                "standard_of_care": soc.get("cards", []),
                "soc_title": soc.get("title"),
                "robotic_sections": [],
                "metrics": block.get("metrics", {}),
            }
        )
        for p in block.get("papers", []):
            _paper_rows(rows, root, topic.key, p, loaded.get(p["id"]))

    robotic = raw[ROBOTIC_KEY]
    rows.tables["topics"].append(
        {
            **ROBOTIC_TOPIC,
            "standard_of_care": [],
            "soc_title": None,
            "robotic_sections": [
                {
                    "slug": section.page.slug,
                    "timeline": robotic[section.page.timeline_key],
                    "cards": robotic[section.page.cards_key],
                    "detailHtml": list(section.details),
                }
                for section in kb.robotic
            ],
            "metrics": robotic.get("metrics", {}),
        }
    )

    for story in news:
        status, published = _review(story)
        if not status:
            rows.errors.append(f"news {story['id']} has no review status")
        rows.tables["news"].append(
            {
                "id": story["id"],
                "paper_id": story["paperId"],
                "published_at": story["publishedAt"],
                "headline": story["headline"],
                "dek": story["dek"],
                "key": story["key"],
                "figures": story["figures"],
                "figure_note": story.get("figureNote"),
                "body": story["body"],
                "review_status": status,
                "review_published_at": published,
            }
        )
    return rows


def _paper_rows(rows: Rows, root: Path, topic_key: str, p: dict, loaded: Any) -> None:
    file = p.get("file")
    if file:
        if not (root / file).is_file():
            rows.errors.append(f"paper {p['id']} points to a missing document: {file}")
        else:
            rows.sources[file] = _sha256((root / file).read_bytes())
    status, published = _review(p)
    rows.tables["papers"].append(
        {
            "id": p["id"],
            "slug": loaded.slug,
            "topic_key": topic_key,
            "year": p["year"],
            "journal": p["journal"],
            "study_type": p["studyType"],
            "n": p.get("n"),
            "regimen": p["regimen"],
            "endpoint": p["endpoint"],
            "result": p["result"],
            "bottom_line": p["bottomLine"],
            "doi": p.get("doi") or None,
            "source": p["source"],
            "reviewed_at": p["reviewedAt"],
            "review_status": status,
            "review_published_at": published,
            "detail_html": loaded.detail_html,
            "source_file": file or None,
        }
    )
    rows.tables["paper_relations"] += [
        {"paper_id": p["id"], "target_id": r["targetId"], "type": r["type"]}
        for r in {(r["targetId"], r["type"]): r for r in p.get("relations", [])}.values()
    ]
    for c in p.get("commentary", []):
        c_status, c_published = _review(c)
        rows.tables["research_commentary"].append(
            {
                "paper_id": p["id"],
                "doi": c.get("doi") or None,
                "pmid": c.get("pmid") or None,
                "title": c["title"],
                "journal": c["journal"],
                "year": c.get("year"),
                "type": c["type"],
                "summary": c["summary"],
                "critique": c["critique"],
                "new_data": c["newData"],
                "added_at": c["addedAt"],
                "review_status": c_status,
                "review_published_at": c_published,
            }
        )


def manifest(rows: Rows) -> dict[str, Any]:
    """Counts and content hashes per table, plus source file hashes, so two imports can be compared exactly."""
    tables = {}
    for name, items in rows.tables.items():
        canonical = sorted(json.dumps(item, sort_keys=True, ensure_ascii=False) for item in items)
        tables[name] = {"count": len(items), "sha256": _sha256("\n".join(canonical).encode())}
    return {"sources": dict(sorted(rows.sources.items())), "tables": tables}


def apply(conn: Any, rows: Rows, *, dry_run: bool = False) -> dict[str, dict[str, int]]:
    """Write all rows in one transaction and return per-table change counts. dry_run rolls back at the end."""
    from psycopg import Rollback, sql
    from psycopg.types.json import Jsonb

    def values(table: str, item: dict) -> list[Any]:
        return [Jsonb(item[c]) if c in JSON_COLUMNS[table] and item[c] is not None else item[c] for c in COLUMNS[table]]

    def upsert(cur: Any, table: LiteralString) -> dict[str, int]:
        cols = COLUMNS[table]
        key = PRIMARY_KEYS[table]
        updates = [c for c in cols if c != key]
        target = [*updates, "withdrawn_at"] if table != "topics" else updates
        query = sql.SQL(
            "insert into app.{table} ({cols}) values ({params}) on conflict ({key}) do update set {sets}"
            " where ({old}) is distinct from ({new}) returning (xmax = 0)"
        ).format(
            table=sql.Identifier(table),
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            params=sql.SQL(", ").join(sql.Placeholder() * len(cols)),
            key=sql.Identifier(key),
            sets=sql.SQL(", ").join(
                sql.SQL("{0} = {1}").format(
                    sql.Identifier(c),
                    sql.SQL("null") if c == "withdrawn_at" else sql.SQL("excluded.{}").format(sql.Identifier(c)),
                )
                for c in target
            ),
            old=sql.SQL(", ").join(sql.SQL("{}.{}").format(sql.Identifier(table), sql.Identifier(c)) for c in target),
            new=sql.SQL(", ").join(
                sql.SQL("null") if c == "withdrawn_at" else sql.SQL("excluded.{}").format(sql.Identifier(c))
                for c in target
            ),
        )
        inserted = updated = 0
        for item in rows.tables[table]:
            cur.execute(query, values(table, item))
            result = cur.fetchone()
            if result:
                inserted += result[0]
                updated += not result[0]
        return {"inserted": inserted, "updated": updated, "unchanged": len(rows.tables[table]) - inserted - updated}

    def withdraw(cur: Any, table: LiteralString) -> int:
        ids = [item["id"] for item in rows.tables[table]]
        cur.execute(
            sql.SQL("update app.{} set withdrawn_at = now() where withdrawn_at is null and not (id = any(%s))").format(
                sql.Identifier(table)
            ),
            (ids,),
        )
        return cur.rowcount

    def replace_children(cur: Any, table: LiteralString) -> dict[str, int]:
        paper_ids = [item["id"] for item in rows.tables["papers"]]
        cur.execute(sql.SQL("delete from app.{} where paper_id = any(%s)").format(sql.Identifier(table)), (paper_ids,))
        removed = cur.rowcount
        cols = COLUMNS[table]
        cur.executemany(
            sql.SQL("insert into app.{} ({}) values ({})").format(
                sql.Identifier(table),
                sql.SQL(", ").join(map(sql.Identifier, cols)),
                sql.SQL(", ").join(sql.Placeholder() * len(cols)),
            ),
            [values(table, item) for item in rows.tables[table]],
        )
        return {"removed": removed, "written": len(rows.tables[table])}

    changes: dict[str, dict[str, int]] = {}
    with conn.transaction(), conn.cursor() as cur:
        for table in ("topics", "papers", "news"):
            try:
                changes[table] = upsert(cur, table)
                if table != "topics":
                    changes[table]["withdrawn"] = withdraw(cur, table)
            except Exception as exc:
                raise RuntimeError(f"import failed in app.{table}: {exc}") from exc
            if table == "papers":
                for child in ("paper_relations", "research_commentary"):
                    try:
                        changes[child] = replace_children(cur, child)
                    except Exception as exc:
                        raise RuntimeError(f"import failed in app.{child}: {exc}") from exc
        if dry_run:
            raise Rollback()
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=os.environ.get("GUTHUB_IMPORT_DATABASE_URL"))
    parser.add_argument("--dry-run", action="store_true", help="roll back instead of committing")
    parser.add_argument("--manifest", type=Path, help="write the manifest JSON here")
    args = parser.parse_args(argv)

    rows = build_rows()
    if rows.errors:
        print("Import stopped before touching the database:", *rows.errors, sep="\n  ", file=sys.stderr)
        return 1
    result: dict[str, Any] = {"manifest": manifest(rows)}
    if args.database_url:
        import psycopg

        with psycopg.connect(args.database_url) as conn:
            try:
                result["changes"] = apply(conn, rows, dry_run=args.dry_run)
            except RuntimeError as exc:
                print(f"Rolled back, nothing was written: {exc}", file=sys.stderr)
                return 1
        result["committed"] = not args.dry_run
    elif not args.dry_run:
        parser.error("--database-url (or GUTHUB_IMPORT_DATABASE_URL) is required unless --dry-run is given")
    if args.manifest:
        args.manifest.write_text(json.dumps(result["manifest"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "manifest"} | {"tables": result["manifest"]["tables"]}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
