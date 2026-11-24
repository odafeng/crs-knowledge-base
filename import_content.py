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
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, LiteralString

from newsroom.gate import unsupported


@dataclass(frozen=True)
class Topic:
    key: str
    slug: str
    label: str
    title: str


@dataclass(frozen=True)
class RoboticPage:
    slug: str
    title: str
    timeline_key: str
    cards_key: str


TOPICS: tuple[Topic, ...] = (
    Topic("mCRC-BRAF-V600E", "braf-v600e", "BRAF V600E", "BRAF V600E 突變型 mCRC"),
    Topic("mCRC-KRAS-G12C", "kras-g12c", "KRAS G12C", "KRAS G12C 突變型 mCRC"),
    Topic("mCRC-MSI-H", "msi-h", "MSI-H / dMMR", "MSI-H / dMMR 大腸直腸癌"),
    Topic("mCRC-HER2", "her2", "HER2", "HER2 陽性 mCRC"),
    Topic("mCRC-RAS-wt", "ras-wt", "RAS wild-type", "RAS 野生型 mCRC"),
    Topic("generic-CRS", "later-line", "後線治療", "mCRC 後線治療與跨分子型"),
)
ROBOTIC_KEY = "robotic-surgery"
ROBOTIC_PAGES: tuple[RoboticPage, ...] = (
    RoboticPage("tme", "機器手臂 TME", "tl_tme", "tme_cards"),
    RoboticPage("anastomosis", "機器手臂吻合", "tl_anast", "anast_cards"),
)
FIGURE_KINDS = frozenset({"numbers", "compare", "meters", "interval"})

ROOT = Path(__file__).resolve().parent
ROBOTIC_TOPIC = {"key": ROBOTIC_KEY, "slug": "robotic", "label": "機器手臂手術", "title": "機器手臂手術"}


def _slug(paper_id: str) -> str:
    return paper_id.lower().replace("_", "-")


def _clean_html(html: str) -> str:
    """Drop empty header corner cells and legacy links into docs/ while keeping their text."""
    html = re.sub(r"<th>\s*</th>", "<td></td>", html)
    return re.sub(r'<a\b[^>]*href="docs/[^"]*"[^>]*>(.*?)</a>', r"\1", html, flags=re.S)


def _detail(root: Path, filename: str | None) -> str:
    if not filename or not (root / filename).is_file():
        return ""
    text = (root / filename).read_text(encoding="utf-8")
    body = re.search(r"<body[^>]*>(.*?)</body>", text, re.S | re.I)
    if not body:
        raise ValueError(f"Missing body in {filename}")
    text = re.sub(r"</?h1\b", lambda m: m[0].replace("h1", "h3"), body[1])
    text = re.sub(r"</?h2\b", lambda m: m[0].replace("h2", "h3"), text)
    text = re.sub(r'\sstyle="[^"]*"', "", text)
    return _clean_html(text)


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
        "added_at",
        "summary",
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
    "papers": {"n", "summary"},
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
    known = {t.key for t in TOPICS} | {ROBOTIC_KEY}
    rows.errors += [f"unknown topic in papers.json: {key}" for key in raw if key not in known]
    for key in known:
        if key not in raw:
            rows.errors.append(f"missing topic in papers.json: {key}")
    if rows.errors:
        return rows
    if raw.get(ROBOTIC_KEY, {}).get("papers"):
        rows.errors.append(f"{ROBOTIC_KEY} papers are not loaded by the site and cannot be imported")

    sources = {p["id"]: p for block in raw.values() for p in block.get("papers", [])}
    for story in news:
        if story["paperId"] not in sources:
            rows.errors.append(f"knowledge base does not load: Unknown source paper: {story['paperId']}")
            continue
        missing = unsupported(story, sources[story["paperId"]])
        if missing:
            rows.errors.append(
                f"knowledge base does not load: Unsupported numbers in {story['id']}: {', '.join(missing)}"
            )
        for fig in story.get("figures", []):
            if fig.get("kind") not in FIGURE_KINDS:
                rows.errors.append(f"knowledge base does not load: unknown figure kind: {fig.get('kind')}")
    if rows.errors:
        return rows

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
            try:
                detail_html = _detail(root, p.get("file"))
            except ValueError as exc:
                rows.errors.append(f"knowledge base does not load: {exc}")
                return rows
            _paper_rows(rows, root, topic.key, p, detail_html)

    robotic = raw[ROBOTIC_KEY]
    robotic_sections = []
    for page in ROBOTIC_PAGES:
        timeline = robotic[page.timeline_key]
        details = []
        for t in timeline:
            if t.get("file", "").startswith("docs/"):
                try:
                    details.append(_detail(root, t["file"]))
                except ValueError as exc:
                    rows.errors.append(f"knowledge base does not load: {exc}")
                    return rows
        robotic_sections.append(
            {
                "slug": page.slug,
                "timeline": timeline,
                "cards": robotic[page.cards_key],
                "detailHtml": details,
            }
        )
    rows.tables["topics"].append(
        {
            **ROBOTIC_TOPIC,
            "standard_of_care": [],
            "soc_title": None,
            "robotic_sections": robotic_sections,
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


def _paper_rows(rows: Rows, root: Path, topic_key: str, p: dict, detail_html: str) -> None:
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
            "slug": _slug(p["id"]),
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
            "detail_html": detail_html,
            "source_file": file or None,
            "added_at": p.get("addedAt"),
            "summary": p.get("summary"),
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


class WriterError(RuntimeError):
    """The database is not in the writer mode this write needs (E2 #73)."""


def check_writer(conn: Any, expected: str) -> None:
    """Locks the writer row for this transaction and refuses to write unless the database is in `expected` mode."""
    row = conn.execute("select writer from app.content_writer for update").fetchone()
    writer = row[0] if row else None
    if writer != expected:
        raise WriterError(
            f"content writer is {writer!r}, not {expected!r}: "
            + (
                "the database is the authority now; export it instead of importing JSON"
                if writer == "postgres"
                else "the database is not the authority yet (content_writer.py cutover)"
            )
        )


def apply(conn: Any, rows: Rows, *, dry_run: bool = False, writer: str = "json") -> dict[str, dict[str, int]]:
    """Write all rows in one transaction and return per-table change counts. dry_run rolls back at the end.

    `writer` is the mode the database must be in: the JSON import runs only before cutover, and the database writer
    (scripts/content_store.py) reuses this after it.
    """
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
        check_writer(conn, writer)
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


def export_kb(conn: Any, root: Path) -> None:
    """Write the database's public content back as data/papers.json, data/news.json and docs/ under `root` (E2 #73).

    The inverse of build_rows for everything not withdrawn: build_rows(root) afterwards yields the same rows, so the
    manifest matches. Detail documents are written as minimal pages holding the stored detail HTML, which is what the
    site reads from them. Order: papers by year (newest first) then ID; news newest first, as the API lists them.
    """
    from psycopg.rows import dict_row

    def rows(query: LiteralString, *params: Any) -> list[dict[str, Any]]:
        with conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(query, params).fetchall()

    def review(status: str | None, published: Any) -> dict[str, Any]:
        if not status:
            return {}
        return {"review": {"status": status, **({"publishedAt": published.isoformat()} if published else {})}}

    def document(path: str, html: str) -> None:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"<!doctype html>\n<html><body>{html}</body></html>\n", encoding="utf-8")

    topics = {t["key"]: t for t in rows("select * from app.topics")}
    relations: dict[str, list[dict[str, str]]] = {}
    for r in rows("select paper_id, target_id, type from app.paper_relations order by paper_id, target_id, type"):
        relations.setdefault(r["paper_id"], []).append({"targetId": r["target_id"], "type": r["type"]})
    commentary: dict[str, list[dict[str, Any]]] = {}
    for c in rows("select * from app.research_commentary order by paper_id, added_at, coalesce(doi, pmid, title)"):
        item = {k: v for k, v in (("doi", c["doi"]), ("pmid", c["pmid"])) if v}
        item |= {"title": c["title"], "journal": c["journal"]}
        item |= {"year": c["year"]} if c["year"] is not None else {}
        item |= {"type": c["type"], "summary": c["summary"], "critique": c["critique"], "newData": c["new_data"]}
        item |= {"addedAt": c["added_at"].isoformat()} | review(c["review_status"], c["review_published_at"])
        commentary.setdefault(c["paper_id"], []).append(item)

    raw: dict[str, Any] = {}
    for topic in TOPICS:
        t = topics.get(topic.key)
        block: dict[str, Any] = {"papers": []}
        if t and (t["soc_title"] is not None or t["standard_of_care"]):
            block["standard_of_care"] = {
                **({"title": t["soc_title"]} if t["soc_title"] is not None else {}),
                "cards": t["standard_of_care"],
            }
        block["metrics"] = t["metrics"] if t else {}
        raw[topic.key] = block
    for p in rows("select * from app.papers where withdrawn_at is null order by year desc, id"):
        entry: dict[str, Any] = {
            "id": p["id"],
            "year": p["year"],
            "journal": p["journal"],
            "studyType": p["study_type"],
            "n": p["n"],
            "regimen": p["regimen"],
            "endpoint": p["endpoint"],
            "result": p["result"],
            "bottomLine": p["bottom_line"],
            "doi": p["doi"] or "",
            "relations": relations.get(p["id"], []),
            "source": p["source"],
            "reviewedAt": p["reviewed_at"].isoformat(),
        }
        if p["added_at"]:
            entry["addedAt"] = p["added_at"].isoformat()
        if p["source_file"]:
            entry["file"] = p["source_file"]
            document(p["source_file"], p["detail_html"])
        if p["id"] in commentary:
            entry["commentary"] = commentary[p["id"]]
        if p["summary"]:
            entry["summary"] = p["summary"]
        entry |= review(p["review_status"], p["review_published_at"])
        raw[p["topic_key"]]["papers"].append(entry)

    robotic = topics.get(ROBOTIC_KEY) or {"robotic_sections": [], "metrics": {}}
    block = {"papers": [], "metrics": robotic.get("metrics", {})}
    sections = {s["slug"]: s for s in robotic["robotic_sections"]}
    for page in ROBOTIC_PAGES:
        section = sections.get(page.slug, {"timeline": [], "cards": [], "detailHtml": []})
        block[page.timeline_key], block[page.cards_key] = section["timeline"], section["cards"]
        details = iter(section["detailHtml"])
        for item in section["timeline"]:
            if item.get("file", "").startswith("docs/"):
                document(item["file"], next(details, ""))
    raw[ROBOTIC_KEY] = block

    news = []
    for n in rows(
        "select n.* from app.news n join app.papers p on p.id = n.paper_id"
        " where n.withdrawn_at is null and p.withdrawn_at is null order by n.published_at desc, n.id"
    ):
        story = {"id": n["id"], "paperId": n["paper_id"], "publishedAt": n["published_at"].isoformat()}
        story |= {"headline": n["headline"], "dek": n["dek"], "key": n["key"], "figures": n["figures"]}
        story |= {"figureNote": n["figure_note"]} if n["figure_note"] is not None else {}
        story |= {"body": n["body"]} | review(n["review_status"], n["review_published_at"])
        news.append(story)

    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data/papers.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "data/news.json").write_text(json.dumps(news, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
