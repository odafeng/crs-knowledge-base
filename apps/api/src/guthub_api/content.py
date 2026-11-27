"""Public read endpoints for papers, news, topics and search (B5 #62, K6 #256).

Reads only the app.public_* views, so withdrawn content never leaves the database. Rich HTML fields are sanitized
at write time with the allowlist below (import_content.py) and plain-text columns are stored unescaped in PostgreSQL.
"""

import base64
import binascii
import json
from datetime import date
from typing import Annotated, Any, Literal, LiteralString, get_args

import nh3
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from guthub_api.db import Conn, get_conn
from guthub_api.taxonomy import DOMAIN_ORDER, DomainSlug

# Contract TopicKey enum, in the contract's (and site's) display order.
type TopicKey = Literal[
    "mCRC-BRAF-V600E", "mCRC-KRAS-G12C", "mCRC-MSI-H", "mCRC-HER2", "mCRC-RAS-wt", "generic-CRS", "robotic-surgery"
]
TOPIC_ORDER: tuple[str, ...] = get_args(TopicKey.__value__)

ALLOWED_TAGS = {"a", "br", "div", "em", "h3", "li", "ol", "p", "s", "strong", "table", "tbody", "td", "th", "thead"}
ALLOWED_TAGS |= {"tr", "ul"}
ALLOWED_ATTRIBUTES = {"a": {"href"}, "div": {"class"}, "p": {"class"}, "td": {"colspan", "rowspan"}}
ALLOWED_ATTRIBUTES["th"] = ALLOWED_ATTRIBUTES["td"]

PUBLIC_CACHE = "public, max-age=300"

router = APIRouter()
type Db = Annotated[Conn, Depends(get_conn)]
type Limit = Annotated[int, Query(ge=1, le=100)]
type Cursor = Annotated[str | None, Query()]


def clean(html: str) -> str:
    return nh3.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)


# --- pagination --------------------------------------------------------------------------------------------------
# The cursor is an opaque offset. Content is small and changes a few times a week, so the rare shift between pages
# is an accepted trade-off for simple, uniform paging (including search across two kinds of results).


def _offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor.encode()))["o"]
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HTTPException(status_code=422, detail="Invalid cursor")
    return value


def _next_cursor(offset: int, limit: int, fetched: int) -> str | None:
    if fetched <= limit:
        return None
    return base64.urlsafe_b64encode(json.dumps({"o": offset + limit}).encode()).decode()


def _page(response: Response, items: list[Any], offset: int, limit: int) -> dict[str, Any]:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return {"items": items[:limit], "nextCursor": _next_cursor(offset, limit, len(items))}


# --- mapping -------------------------------------------------------------------------------------------------------


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _review(row: dict[str, Any]) -> dict[str, Any]:
    if not row["review_status"]:
        return {}
    review = {"status": row["review_status"]}
    if row["review_published_at"]:
        review["publishedAt"] = _iso(row["review_published_at"])
    return {"review": review}


def _papers(db: Conn, rows: list[dict[str, Any]], *, include_detail: bool = True) -> list[dict[str, Any]]:
    ids = [row["id"] for row in rows]
    relations: dict[str, list[dict[str, str]]] = {}
    commentary: dict[str, list[dict[str, Any]]] = {}
    paper_domains: dict[str, list[dict[str, Any]]] = {}
    # Relations to withdrawn papers are dropped: their targets are not public.
    for r in db.execute(
        "select r.paper_id, r.target_id, r.type::text from app.paper_relations r"
        " join app.public_papers t on t.id = r.target_id where r.paper_id = any(%s)"
        " order by r.paper_id, r.target_id, r.type",
        (ids,),
    ):
        relations.setdefault(r["paper_id"], []).append({"targetId": r["target_id"], "type": r["type"]})
    for c in db.execute(
        "select * from app.research_commentary where paper_id = any(%s) order by id",
        (ids,),
    ):
        commentary.setdefault(c["paper_id"], []).append(
            {
                "doi": c["doi"],
                "pmid": c["pmid"],
                "title": c["title"],
                "journal": c["journal"],
                "year": c["year"],
                "type": c["type"],
                "summary": c["summary"],
                "critique": c["critique"],
                "newData": c["new_data"],
                "addedAt": _iso(c["added_at"]),
                **_review(c),
            }
        )
    for d in db.execute(
        "select paper_id, domain_slug, is_primary, subtopic_id from app.paper_domains"
        " where paper_id = any(%s) order by paper_id, is_primary desc, array_position(%s::text[], domain_slug)",
        (ids, list(DOMAIN_ORDER)),
    ):
        paper_domains.setdefault(d["paper_id"], []).append(d)

    def _taxonomy_fields(paper_id: str) -> dict[str, Any]:
        links = paper_domains.get(paper_id)
        if not links:
            return {}
        primary = next((link["domain_slug"] for link in links if link["is_primary"]), None)
        secondaries = [link["domain_slug"] for link in links if not link["is_primary"]]
        subtopics = list(dict.fromkeys(link["subtopic_id"] for link in links if link["subtopic_id"]))
        fields: dict[str, Any] = {}
        if primary is not None:
            fields["primaryDomain"] = primary
            fields["secondaryDomains"] = secondaries
            fields["subtopics"] = subtopics
        return fields

    return [
        {
            "id": row["id"],
            "slug": row["slug"],
            "topic": row["topic_key"],
            "year": row["year"],
            "journal": row["journal"],
            "studyType": row["study_type"],
            "n": row["n"],
            "regimen": row["regimen"],
            "endpoint": row["endpoint"],
            "result": row["result"],
            "bottomLine": row["bottom_line"],
            "doi": row["doi"],
            "relations": relations.get(row["id"], []),
            "source": row["source"],
            "reviewedAt": _iso(row["reviewed_at"]),
            **({"addedAt": _iso(row["added_at"])} if row["added_at"] else {}),
            **_review(row),
            "commentary": commentary.get(row["id"], []),
            "detailHtml": row["detail_html"] if include_detail else "",
            **({"summary": row["summary"]} if row["summary"] else {}),
            **_taxonomy_fields(row["id"]),
        }
        for row in rows
    ]


def _news(row: dict[str, Any]) -> dict[str, Any]:
    review: dict[str, Any] = {"status": row["review_status"]}
    if row["review_published_at"]:
        review["publishedAt"] = _iso(row["review_published_at"])
    item = {
        "id": row["id"],
        "paperId": row["paper_id"],
        "publishedAt": _iso(row["published_at"]),
        "headline": row["headline"],
        "dek": row["dek"],
        "key": row["key"],
        "figures": row["figures"],
        "body": row["body"],
        "review": review,
    }
    if row["figure_note"] is not None:
        item["figureNote"] = row["figure_note"]
    return item


def _topic(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": row["key"],
        "slug": row["slug"],
        "label": row["label"],
        "title": row["title"],
        "paperCount": row["paper_count"],
        "standardOfCare": row["standard_of_care"],
        "roboticSections": row["robotic_sections"],
    }


# --- papers --------------------------------------------------------------------------------------------------------


PAPER_LIST_QUERY_FULL: LiteralString = (
    "select * from app.public_papers p"
    " where (%(topic)s::text is null or p.topic_key = %(topic)s)"
    " and (%(domain)s::text is null or exists ("
    "   select 1 from app.paper_domains pd where pd.paper_id = p.id and pd.domain_slug = %(domain)s))"
    " order by p.year desc, p.id limit %(limit)s offset %(offset)s"
)
PAPER_LIST_QUERY_SLIM: LiteralString = (
    "select p.id, p.slug, p.topic_key, p.year, p.journal, p.study_type, p.n, p.regimen, p.endpoint, p.result,"
    " p.bottom_line, p.doi, p.source, p.reviewed_at, p.added_at, p.review_status, p.review_published_at, p.summary"
    " from app.public_papers p"
    " where (%(topic)s::text is null or p.topic_key = %(topic)s)"
    " and (%(domain)s::text is null or exists ("
    "   select 1 from app.paper_domains pd where pd.paper_id = p.id and pd.domain_slug = %(domain)s))"
    " order by p.year desc, p.id limit %(limit)s offset %(offset)s"
)
type PaperSlug = Annotated[str, Path(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")]


@router.get("/papers")
def list_papers(
    db: Db,
    response: Response,
    limit: Limit = 20,
    cursor: Cursor = None,
    topic: TopicKey | None = None,
    domain: DomainSlug | None = None,
    include_detail: Annotated[bool, Query(alias="includeDetail")] = True,
) -> dict[str, Any]:
    offset = _offset(cursor)
    query = PAPER_LIST_QUERY_FULL if include_detail else PAPER_LIST_QUERY_SLIM
    rows = db.execute(query, {"topic": topic, "domain": domain, "limit": limit + 1, "offset": offset}).fetchall()
    return _page(response, _papers(db, rows, include_detail=include_detail), offset, limit)


@router.get("/papers/by-slug/{slug}")
def get_paper_by_slug(slug: PaperSlug, db: Db, response: Response) -> dict[str, Any]:
    row = db.execute("select * from app.public_papers where slug = %s", (slug,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return _papers(db, [row])[0]


@router.get("/papers/{paper_id}")
def get_paper(paper_id: str, db: Db, response: Response) -> dict[str, Any]:
    row = db.execute("select * from app.public_papers where id = %s", (paper_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return _papers(db, [row])[0]


# --- news ----------------------------------------------------------------------------------------------------------


@router.get("/news")
def list_news(db: Db, response: Response, limit: Limit = 20, cursor: Cursor = None) -> dict[str, Any]:
    offset = _offset(cursor)
    rows = db.execute(
        "select * from app.public_news order by published_at desc, id limit %s offset %s", (limit + 1, offset)
    ).fetchall()
    return _page(response, [_news(row) for row in rows], offset, limit)


@router.get("/news/{news_id}")
def get_news(news_id: str, db: Db, response: Response) -> dict[str, Any]:
    row = db.execute("select * from app.public_news where id = %s", (news_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="News not found")
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return _news(row)


# --- topics --------------------------------------------------------------------------------------------------------

TOPIC_QUERY: LiteralString = (
    "select t.*, (select count(*) from app.public_papers p where p.topic_key = t.key)::int as paper_count"
    " from app.topics t"
)


@router.get("/topics")
def list_topics(db: Db, response: Response, limit: Limit = 20, cursor: Cursor = None) -> dict[str, Any]:
    offset = _offset(cursor)
    rows = db.execute(
        TOPIC_QUERY
        + " where t.kind = 'legacy_subtopic' order by array_position(%s::text[], t.key), t.key limit %s offset %s",
        (list(TOPIC_ORDER), limit + 1, offset),
    ).fetchall()
    return _page(response, [_topic(row) for row in rows], offset, limit)


@router.get("/topics/{topic_key}")
def get_topic(topic_key: TopicKey, db: Db, response: Response) -> dict[str, Any]:
    row = db.execute(TOPIC_QUERY + " where t.key = %s", (topic_key,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return _topic(row)


# --- domains (T1 #282, ADR-0030) -----------------------------------------------------------------------------------

DOMAIN_QUERY: LiteralString = (
    "select d.*, (select count(distinct pd.paper_id) from app.paper_domains pd"
    " join app.public_papers p on p.id = pd.paper_id where pd.domain_slug = d.slug)::int as paper_count"
    " from app.domains d"
)


def _domains(db: Conn, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slugs = [row["slug"] for row in rows]
    subtopics: dict[str, list[dict[str, Any]]] = {}
    if slugs:
        for s in db.execute(
            "select id, parent_domain, slug, label_zh, label_en, legacy_topic_key, route_path, status"
            " from app.subtopics where parent_domain = any(%s) order by parent_domain, sort_order, id",
            (slugs,),
        ):
            subtopics.setdefault(s["parent_domain"], []).append(
                {
                    "id": s["id"],
                    "slug": s["slug"],
                    "labelZh": s["label_zh"],
                    "labelEn": s["label_en"],
                    "legacyTopicKey": s["legacy_topic_key"],
                    "routePath": s["route_path"],
                    "status": s["status"],
                }
            )
    return [
        {
            "slug": row["slug"],
            "order": row["sort_order"],
            "labelZh": row["label_zh"],
            "labelEn": row["label_en"],
            "descriptionZh": row["description_zh"],
            "status": row["status"],
            "registryVersion": row["registry_version"],
            "paperCount": row["paper_count"],
            "subtopics": subtopics.get(row["slug"], []),
        }
        for row in rows
    ]


@router.get("/domains")
def list_domains(db: Db, response: Response, limit: Limit = 20, cursor: Cursor = None) -> dict[str, Any]:
    offset = _offset(cursor)
    rows = db.execute(
        DOMAIN_QUERY + " order by d.sort_order, d.slug limit %s offset %s",
        (limit + 1, offset),
    ).fetchall()
    return _page(response, _domains(db, rows), offset, limit)


@router.get("/domains/{domain_slug}")
def get_domain(domain_slug: DomainSlug, db: Db, response: Response) -> dict[str, Any]:
    row = db.execute(DOMAIN_QUERY + " where d.slug = %s", (domain_slug,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return _domains(db, [row])[0]


# --- search --------------------------------------------------------------------------------------------------------
# Mirrors the site's search index (sitegen/render.py): same fields, same titles, news before papers.

SEARCH_QUERY: LiteralString = """
select * from (
  select 'news' as kind, n.id, '/news/' || n.id || '/' as path,
         (select string_agg(part, '' order by ord) from jsonb_array_elements_text(n.headline) with ordinality h(part, ord))
           as title,
         '最新消息 · ' || t.label as summary, 0 as rank, n.published_at as sort_date, n.id as sort_id
  from app.public_news n
  join app.papers p on p.id = n.paper_id
  join app.topics t on t.key = p.topic_key
  left join app.domains td on td.slug = t.domain_slug
  where n.search_text like %(pattern)s
     or (td.slug is not null and (lower(td.label_zh) like %(pattern)s or lower(td.label_en) like %(pattern)s))
     or exists (
       select 1 from app.paper_domains pd join app.domains d on d.slug = pd.domain_slug
       where pd.paper_id = p.id and (lower(d.label_zh) like %(pattern)s or lower(d.label_en) like %(pattern)s)
     )
  union all
  select 'paper', p.id, '/papers/' || p.slug || '/', p.regimen || '（' || p.journal || ' ' || p.year || '）',
         t.label || ' · ' || p.study_type, 1, make_date(p.year, 1, 1), p.id
  from app.public_papers p
  join app.topics t on t.key = p.topic_key
  left join app.domains td on td.slug = t.domain_slug
  where p.search_text like %(pattern)s
     or (td.slug is not null and (lower(td.label_zh) like %(pattern)s or lower(td.label_en) like %(pattern)s))
     or exists (
       select 1 from app.paper_domains pd join app.domains d on d.slug = pd.domain_slug
       where pd.paper_id = p.id and (lower(d.label_zh) like %(pattern)s or lower(d.label_en) like %(pattern)s)
     )
) hits
order by rank, sort_date desc, sort_id
limit %(limit)s offset %(offset)s
"""


@router.get("/search")
def search(
    db: Db,
    response: Response,
    q: Annotated[str, Query(min_length=2)],
    limit: Limit = 20,
    cursor: Cursor = None,
) -> dict[str, Any]:
    offset = _offset(cursor)
    escaped = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    if len(escaped) < 2:
        raise HTTPException(status_code=422, detail="Search needs at least two characters")
    rows = db.execute(SEARCH_QUERY, {"pattern": f"%{escaped}%", "limit": limit + 1, "offset": offset}).fetchall()
    hits = [
        {
            "kind": row["kind"],
            "id": row["id"],
            "path": row["path"],
            "title": row["title"],
            "summary": row["summary"],
        }
        for row in rows
    ]
    return _page(response, hits, offset, limit)
