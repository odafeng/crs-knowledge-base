"""Automatic plain-language news stories for new Paper Watch papers (K2 #252).

python scripts/news_writer.py [--database-url URL] [--only ID ...] [--dry-run] [--redo]

After Paper Watch auto-publishes high-impact papers, this generates structured Traditional Chinese news stories
(matching contracts/openapi.yaml `News`), verifies every number against the source paper entry via `newsroom/gate.py`
and checks schema/figure bounds, then writes kept stories through `content_session` with `review.status = "auto"`.
Auto-published stories appear in `/admin/review` where the maintainer can mark them reviewed or unpublish them, and
automatically feed the home ticker, LINE morning briefing, and Web Push.
"""

import argparse
import json
import math
import os
import re
import sys
from datetime import UTC, date, datetime
from typing import Any, TypeGuard

from anthropic import Anthropic

from config import ANTHROPIC_API_KEY, CLASSIFY_MODEL, FALLBACK_BETA
from content_store import DATABASE_ENV, content_session
from publish import ROOT, publish_news
from usage import USAGE

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from newsroom.gate import unsupported

MAX_STORIES_PER_RUN = 2
# Only high-impact papers get a story, even though score-3 papers auto-publish (ADR-0032 / K14 #308).
NEWS_SCORE_THRESHOLD = 4
MAJOR_STUDY_TYPES = ("Phase 3", "Phase 2", "Meta-analysis", "Guideline", "Pooled analysis")
NEWS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TAG_RE = re.compile(r"<[A-Za-z/!]")
MIDDLE_DOT = re.compile(r"(?<=\d)·(?=\d)")

REQUIRED_HEADING = "發生了什麼"
CLINICAL_HEADINGS = ("為什麼重要", "對臨床的意義")
INTERVAL_MIN = 0.1
INTERVAL_MAX = 8.0
CI_95_RE = re.compile(r"\b95\s*%\s*(?:ci|confidence\s+interval)\b", re.I)
ANY_CI_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*%\s*(?:ci|confidence\s+interval)\b", re.I)

_STAT_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "指標說明，例如「3 年無病存活率（DFS）」或「中位整體存活（mOS）」"},
        "value": {"type": "string", "description": "純數值字串，必須原樣來自 <entry>，例如「30.3」或「100」"},
        "unit": {"type": "string", "description": '單位，例如「個月」、「%」、「例」，無單位填 ""'},
    },
    "required": ["label", "value", "unit"],
    "additionalProperties": False,
}

_NUMBERS_FIGURE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["numbers"]},
        "stats": {"type": "array", "items": _STAT_SCHEMA, "description": "2 到 4 個關鍵數字"},
    },
    "required": ["kind", "stats"],
    "additionalProperties": False,
}

_COMPARE_FIGURE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["compare"]},
        "armA": {"type": "string", "description": "試驗組短名"},
        "armB": {"type": "string", "description": "對照組短名"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "unit": {"type": "string"},
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["label", "unit", "a", "b"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["kind", "armA", "armB", "rows"],
    "additionalProperties": False,
}

_METERS_FIGURE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["meters"]},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "percent": {"type": "number"},
                    "detail": {"type": "string", "description": '補充說明，無則填 ""'},
                },
                "required": ["label", "percent", "detail"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["kind", "rows"],
    "additionalProperties": False,
}

_INTERVAL_FIGURE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["interval"]},
        "label": {"type": "string"},
        "point": {"type": "number"},
        "low": {"type": "number"},
        "high": {"type": "number"},
        "note": {"type": "string", "description": '簡短註解，無則填 ""'},
    },
    "required": ["kind", "label", "point", "low", "high", "note"],
    "additionalProperties": False,
}

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2 到 4 段短語組成主標（合併總長 12–48 字），例如 [\"BREAKWATER：\", \"一線 EC + mFOLFOX6 \", \"mOS 達 30.3 個月\"]",
        },
        "dek": {
            "type": "string",
            "description": "1 到 2 句白話導言（140 字以內），讓外科醫師一眼看懂這篇研究收了誰、做了什麼、結果為何",
        },
        "key": _STAT_SCHEMA,
        "figures": {
            "type": "array",
            "items": {
                "anyOf": [
                    _NUMBERS_FIGURE_SCHEMA,
                    _COMPARE_FIGURE_SCHEMA,
                    _METERS_FIGURE_SCHEMA,
                    _INTERVAL_FIGURE_SCHEMA,
                ]
            },
            "description": "0 到 2 張資料圖（numbers / compare / meters / interval）；只放 <entry> 明確有數字的圖表，沒足夠數字就回傳 []",
        },
        "figureNote": {
            "type": "string",
            "description": "簡短數字出處與研究設計註記（例如「數字出處：NEJM 2025，Phase 3 RCT。」），無則填 \"\"",
        },
        "body": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {
                        "type": "string",
                        "description": "建議依序使用：「發生了什麼」、「為什麼重要」、「限制」、「對臨床的意義」",
                    },
                    "text": {"type": "string", "description": "白話、具體、短句，不超過 300 字"},
                },
                "required": ["heading", "text"],
                "additionalProperties": False,
            },
            "description": "3 到 4 個段落，必須包含「發生了什麼」以及「為什麼重要」或「對臨床的意義」",
        },
    },
    "required": ["headline", "dek", "key", "figures", "figureNote", "body"],
    "additionalProperties": False,
}  # fmt: skip

SYSTEM = """你替台灣大腸直腸外科實證知識庫 GutHub 撰寫「近期新聞」白話專文。讀者是忙碌的臨床醫師，要在 30 秒內看懂這篇新研究發生了什麼、為什麼重要、有什麼限制、對臨床的意義。

嚴格規則（違反任一條文章會被系統直接拒收）：
1. 文中任何地方出現的所有阿拉伯數字（包含 headline、dek、key、figures、figureNote、body）都必須原樣出現在 <entry> 區塊裡。
2. 絕對不可以自己換算、加減、相除、四捨五入或補上 <entry> 沒寫的數字——例如不能從 HR 0.49 自己算「風險降低 51%」、不能自己寫「2 組」「第 1 線」「95% CI」（除非 2、1、95 真的出現在 <entry> 裡）、不能自己加上未記載的追蹤年數。
3. 藥名、試驗縮寫、指標（mOS、mPFS、HR、ORR、pCR、DFS、cCR 等）保留英文；其餘用台灣臨床白話中文，句子短、直接、客觀，不寫宣傳語氣，不給個別病人的治療建議。
4. 不可使用任何 HTML 標籤。
5. interval 圖表僅在 <entry> 明確提供 95% CI 的點估計與上下界（且數值落在 0.1 到 8.0 之間）時才使用（若原文是 90% CI 或未寫 95% CI，請改用 numbers 圖表）。"""


def is_newsworthy(paper: dict[str, Any], score: int | None = None) -> bool:
    """Whether an auto-published paper should receive an automatic news story."""
    if score is not None and score >= 5:
        return True
    study_type = str(paper.get("studyType") or paper.get("study_type") or "")
    major = any(marker in study_type for marker in MAJOR_STUDY_TYPES)
    if score is not None:
        return score >= NEWS_SCORE_THRESHOLD and major
    return major


def select_candidates(published: list[dict[str, Any]], *, max_stories: int = MAX_STORIES_PER_RUN) -> list[str]:
    """Pick up to `max_stories` newly published paper IDs eligible for auto-generated news."""
    eligible: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for item in published:
        paper_id = item.get("kb_id")
        if not paper_id or paper_id in seen:
            continue
        raw_meta = item.get("ai_suggested_js")
        meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else item
        score = item.get("ai_score")
        if not is_newsworthy(meta, score):
            continue
        seen.add(paper_id)
        study_type = str(meta.get("studyType") or "")
        phase3_rank = 0 if "Phase 3" in study_type else 1
        eligible.append((-int(score or 0), phase3_rank, str(paper_id)))
    eligible.sort()
    return [paper_id for _, _, paper_id in eligible[:max_stories]]


def story_id_for(paper_id: str, taken: set[str]) -> str:
    """Derive a unique news ID matching `^[a-z0-9][a-z0-9-]*$` from a paper ID."""
    base = re.sub(r"[^a-z0-9]+", "-", paper_id.lower()).strip("-") or "story"
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def resolve_story_id(paper_id: str, taken: set[str], existing_by_paper: dict[str, str], *, redo: bool) -> str:
    """Reuse the paper's existing story ID on --redo so published /news/<id>/ links remain valid."""
    if redo and paper_id in existing_by_paper:
        return existing_by_paper[paper_id]
    return story_id_for(paper_id, taken)


def _clean_text(value: str) -> str:
    return MIDDLE_DOT.sub(".", value.strip())


def _is_finite_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _has_html(texts: list[str]) -> bool:
    return any(TAG_RE.search(t) for t in texts)


def _validate_stat(label: str, stat: Any, texts: list[str]) -> list[str]:
    if not isinstance(stat, dict):
        return [f"{label} must be an object"]
    errors = []
    for key, (lo, hi) in (("label", (1, 48)), ("value", (1, 24)), ("unit", (0, 16))):
        val = stat.get(key)
        if not isinstance(val, str) or not (lo <= len(val.strip()) <= hi):
            errors.append(f"{label}.{key} must be {lo}-{hi} characters")
        else:
            texts.append(val)
    extra = set(stat) - {"label", "value", "unit"}
    if extra:
        errors.append(f"{label} has unknown fields: {', '.join(sorted(extra))}")
    return errors


def _validate_figure(index: int, figure: Any, texts: list[str]) -> list[str]:
    label = f"figures[{index}]"
    if not isinstance(figure, dict):
        return [f"{label} must be an object"]
    kind = figure.get("kind")
    errors: list[str] = []
    if kind == "numbers":
        stats = figure.get("stats")
        if not isinstance(stats, list) or not (1 <= len(stats) <= 6):
            errors.append(f"{label}.stats must have 1-6 items")
        else:
            for i, stat in enumerate(stats):
                errors += _validate_stat(f"{label}.stats[{i}]", stat, texts)
    elif kind == "compare":
        for arm in ("armA", "armB"):
            val = figure.get(arm)
            if not isinstance(val, str) or not (1 <= len(val.strip()) <= 40):
                errors.append(f"{label}.{arm} must be 1-40 characters")
            else:
                texts.append(val)
        rows = figure.get("rows")
        if not isinstance(rows, list) or not (1 <= len(rows) <= 5):
            errors.append(f"{label}.rows must have 1-5 items")
        else:
            max_by_unit: dict[str, float] = {}
            for i, row in enumerate(rows):
                if not isinstance(row, dict):
                    errors.append(f"{label}.rows[{i}] must be an object")
                    continue
                for k, (lo, hi) in (("label", (1, 48)), ("unit", (0, 16))):
                    val = row.get(k)
                    if not isinstance(val, str) or not (lo <= len(val.strip()) <= hi):
                        errors.append(f"{label}.rows[{i}].{k} must be {lo}-{hi} characters")
                    else:
                        texts.append(val)
                a, b = row.get("a"), row.get("b")
                if not (_is_finite_number(a) and _is_finite_number(b) and a >= 0 and b >= 0):
                    errors.append(f"{label}.rows[{i}] values must be non-negative finite numbers")
                else:
                    unit = str(row.get("unit", ""))
                    max_by_unit[unit] = max(max_by_unit.get(unit, 0.0), float(a), float(b))
            for unit, top in max_by_unit.items():
                if unit != "%" and top <= 0:
                    errors.append(f"{label} compare rows for unit {unit!r} must have a positive maximum")
    elif kind == "meters":
        rows = figure.get("rows")
        if not isinstance(rows, list) or not (1 <= len(rows) <= 5):
            errors.append(f"{label}.rows must have 1-5 items")
        else:
            for i, row in enumerate(rows):
                if not isinstance(row, dict):
                    errors.append(f"{label}.rows[{i}] must be an object")
                    continue
                lbl = row.get("label")
                if not isinstance(lbl, str) or not (1 <= len(lbl.strip()) <= 48):
                    errors.append(f"{label}.rows[{i}].label must be 1-48 characters")
                else:
                    texts.append(lbl)
                pct = row.get("percent")
                if not (_is_finite_number(pct) and 0 <= pct <= 100):
                    errors.append(f"{label}.rows[{i}].percent must be between 0 and 100")
                detail = row.get("detail")
                if detail is not None:
                    if not isinstance(detail, str) or len(detail.strip()) > 80:
                        errors.append(f"{label}.rows[{i}].detail must be <= 80 characters")
                    else:
                        texts.append(detail)
    elif kind == "interval":
        lbl = figure.get("label")
        if not isinstance(lbl, str) or not (1 <= len(lbl.strip()) <= 48):
            errors.append(f"{label}.label must be 1-48 characters")
        else:
            texts.append(lbl)
        low, point, high = figure.get("low"), figure.get("point"), figure.get("high")
        if not (
            _is_finite_number(low)
            and _is_finite_number(point)
            and _is_finite_number(high)
            and INTERVAL_MIN <= low <= point <= high <= INTERVAL_MAX
        ):
            errors.append(f"{label} requires {INTERVAL_MIN} <= low <= point <= high <= {INTERVAL_MAX}")
        note = figure.get("note")
        if note is not None:
            if not isinstance(note, str) or len(note.strip()) > 80:
                errors.append(f"{label}.note must be <= 80 characters")
            else:
                texts.append(note)
    else:
        errors.append(f"{label} has unknown kind: {kind!r}")
    return errors


def validate_story(story: dict[str, Any]) -> list[str]:
    """Validate a news story's shape, bounds, required sections, and absence of raw HTML."""
    errors: list[str] = []
    texts: list[str] = []

    sid = story.get("id")
    if not isinstance(sid, str) or not NEWS_ID_RE.match(sid):
        errors.append("id must match ^[a-z0-9][a-z0-9-]*$")
    if not isinstance(story.get("paperId"), str) or not story["paperId"].strip():
        errors.append("paperId is required")
    if not isinstance(story.get("publishedAt"), str) or not DATE_RE.match(story["publishedAt"]):
        errors.append("publishedAt must be YYYY-MM-DD")

    headline = story.get("headline")
    if (
        not isinstance(headline, list)
        or not (2 <= len(headline) <= 4)
        or not all(isinstance(p, str) and p.strip() for p in headline)
    ):
        errors.append("headline must be 2-4 non-empty strings")
    else:
        combined = "".join(headline).strip()
        if not (4 <= len(combined) <= 60):
            errors.append("headline combined length must be 4-60 characters")
        texts.extend(headline)

    dek = story.get("dek")
    if not isinstance(dek, str) or not (1 <= len(dek.strip()) <= 180):
        errors.append("dek must be 1-180 characters")
    else:
        texts.append(dek)

    errors += _validate_stat("key", story.get("key"), texts)

    figures = story.get("figures")
    if not isinstance(figures, list) or len(figures) > 2:
        errors.append("figures must be a list of 0-2 items")
    else:
        for i, fig in enumerate(figures):
            errors += _validate_figure(i, fig, texts)

    figure_note = story.get("figureNote")
    if figure_note is not None:
        if not isinstance(figure_note, str) or len(figure_note.strip()) > 160:
            errors.append("figureNote must be <= 160 characters")
        else:
            texts.append(figure_note)

    body = story.get("body")
    if not isinstance(body, list) or not (2 <= len(body) <= 4):
        errors.append("body must have 2-4 sections")
    else:
        headings: list[str] = []
        for i, sec in enumerate(body):
            if not isinstance(sec, dict):
                errors.append(f"body[{i}] must be an object")
                continue
            h, t = sec.get("heading"), sec.get("text")
            if not isinstance(h, str) or not (1 <= len(h.strip()) <= 24):
                errors.append(f"body[{i}].heading must be 1-24 characters")
            else:
                headings.append(h.strip())
                texts.append(h)
            if not isinstance(t, str) or not (1 <= len(t.strip()) <= 360):
                errors.append(f"body[{i}].text must be 1-360 characters")
            else:
                texts.append(t)
        if REQUIRED_HEADING not in headings:
            errors.append(f"body must include a '{REQUIRED_HEADING}' section")
        if not any(h in headings for h in CLINICAL_HEADINGS):
            errors.append("body must include '為什麼重要' or '對臨床的意義'")

    review = story.get("review")
    if not isinstance(review, dict) or review.get("status") not in ("auto", "accepted"):
        errors.append("review.status must be 'auto' or 'accepted'")
    elif review.get("publishedAt") is not None and not DATE_RE.match(str(review["publishedAt"])):
        errors.append("review.publishedAt must be YYYY-MM-DD")

    if _has_html(texts):
        errors.append("story contains raw HTML")
    return errors


def problems(story: dict[str, Any], paper: dict[str, Any]) -> list[str]:
    """Why a generated story cannot be published: shape/bounds errors or numbers absent from the source paper entry."""
    found = validate_story(story)
    source = entry_text(paper)
    for idx, fig in enumerate(story.get("figures") or []):
        if isinstance(fig, dict) and fig.get("kind") == "interval":
            if not CI_95_RE.search(source):
                found.append(f"figures[{idx}] interval requires a source-confirmed 95% CI in <entry>")
            note = str(fig.get("note") or "")
            non_95 = [lvl for lvl in ANY_CI_RE.findall(note) if float(lvl) != 95.0]
            if non_95:
                found.append(f"figures[{idx}] interval cannot label a {', '.join(non_95)}% CI as 95% CI")
    try:
        missing = unsupported(story, paper)
    except KeyError as exc:
        return [*found, f"missing story field: {exc}"]
    if missing:
        found.append(f"numbers not in <entry>: {', '.join(missing)}")
    return found


def entry_text(paper: dict[str, Any]) -> str:
    keys = ("regimen", "studyType", "n", "endpoint", "result", "bottomLine", "journal", "year")
    return "\n".join(f"{k}: {paper[k]}" for k in keys if paper.get(k) is not None)


def _normalize_figures(raw_figures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for fig in raw_figures:
        kind = fig.get("kind")
        if kind == "numbers":
            cleaned.append(
                {
                    "kind": "numbers",
                    "stats": [
                        {
                            "label": _clean_text(s["label"]),
                            "value": _clean_text(s["value"]),
                            "unit": _clean_text(s.get("unit", "")),
                        }
                        for s in fig.get("stats", [])
                    ],
                }
            )
        elif kind == "compare":
            cleaned.append(
                {
                    "kind": "compare",
                    "armA": _clean_text(fig["armA"]),
                    "armB": _clean_text(fig["armB"]),
                    "rows": [
                        {
                            "label": _clean_text(r["label"]),
                            "unit": _clean_text(r.get("unit", "")),
                            "a": r["a"],
                            "b": r["b"],
                        }
                        for r in fig.get("rows", [])
                    ],
                }
            )
        elif kind == "meters":
            rows = []
            for r in fig.get("rows", []):
                item: dict[str, Any] = {"label": _clean_text(r["label"]), "percent": r["percent"]}
                detail = _clean_text(r.get("detail", ""))
                if detail:
                    item["detail"] = detail
                rows.append(item)
            cleaned.append({"kind": "meters", "rows": rows})
        elif kind == "interval":
            item = {
                "kind": "interval",
                "label": _clean_text(fig["label"]),
                "point": fig["point"],
                "low": fig["low"],
                "high": fig["high"],
            }
            note = _clean_text(fig.get("note", ""))
            if note:
                item["note"] = note
            cleaned.append(item)
    return cleaned


def write(
    client: Anthropic,
    paper: dict[str, Any],
    story_id: str,
    today: str,
    refused: list[str] | None = None,
) -> dict[str, Any]:
    prompt = f"<entry>\n{entry_text(paper)}\n</entry>\n"
    if isinstance(paper.get("summary"), dict):
        summary = paper["summary"]
        prompt += (
            "\n<context>\n"
            f"title: {summary.get('title', '')}\n"
            f"takeaway: {summary.get('takeaway', '')}\n"
            f"meaning: {summary.get('meaning', '')}\n"
            "</context>\n"
        )
    prompt += "\n請依 <entry> 撰寫一篇白話中文新聞專文。提醒：所有數字一律只能來自 <entry>，不可使用 <context> 或自行推算的新數字。"
    if refused:
        prompt += "\n\n上一版沒有通過檢查，請修正後重寫：\n" + "\n".join(f"- {r}" for r in refused)
        prompt += "\n所有數字都必須原樣出現在 <entry> 裡；找不到出處的數字請直接刪除或改用文字描述。"

    response = client.beta.messages.create(
        model=CLASSIFY_MODEL,
        max_tokens=16000,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    USAGE.record(response, CLASSIFY_MODEL)
    if response.stop_reason != "end_turn":
        raise ValueError(f"stopped: {response.stop_reason}")
    raw = json.loads(next(b.text for b in response.content if b.type == "text"))

    story: dict[str, Any] = {
        "id": story_id,
        "paperId": paper["id"],
        "publishedAt": today,
        "headline": [_clean_text(part) for part in raw["headline"] if part.strip()],
        "dek": _clean_text(raw["dek"]),
        "key": {
            "label": _clean_text(raw["key"]["label"]),
            "value": _clean_text(raw["key"]["value"]),
            "unit": _clean_text(raw["key"].get("unit", "")),
        },
        "figures": _normalize_figures(raw.get("figures", [])),
        "body": [{"heading": _clean_text(s["heading"]), "text": _clean_text(s["text"])} for s in raw["body"]],
        "review": {"status": "auto", "publishedAt": today},
    }
    note = _clean_text(raw.get("figureNote", ""))
    if note:
        story["figureNote"] = note
    return story


def draft(client: Anthropic, paper: dict[str, Any], story_id: str, today: str) -> tuple[dict[str, Any], list[str]]:
    """Draft one story and validate it; if refused, retry once with the exact refusal reasons."""
    story = write(client, paper, story_id, today)
    found = problems(story, paper)
    if found:
        story = write(client, paper, story_id, today, found)
        found = problems(story, paper)
    return story, found


def save(story: dict[str, Any], conn: Any = None, *, replace: bool = False) -> None:
    """Persist one news story through the content writer (idempotent via app.publish_events)."""
    with content_session("publish_news", story["id"], conn=conn) as session:
        if session.done is not None:
            return
        publish_news(story, session.kb, replace=replace)
        session.record(f"news {story['id']} ({story['paperId']})")


def _load_db_state(conn: Any) -> tuple[list[dict[str, Any]], set[str], dict[str, str]]:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        paper_rows = cur.execute(
            "select id, regimen, study_type, n, endpoint, result, bottom_line, journal, year, summary"
            " from app.papers where withdrawn_at is null order by year desc, id"
        ).fetchall()
        news_rows = cur.execute(
            "select id, paper_id from app.news order by (withdrawn_at is not null), published_at desc, id"
        ).fetchall()
    names = {"study_type": "studyType", "bottom_line": "bottomLine"}
    papers = [{names.get(str(k), str(k)): v for k, v in row.items()} for row in paper_rows]
    taken_ids = {str(r["id"]) for r in news_rows}
    existing_by_paper: dict[str, str] = {}
    for r in news_rows:
        existing_by_paper.setdefault(str(r["paper_id"]), str(r["id"]))
    return papers, taken_ids, existing_by_paper


def run(
    url: str,
    only: list[str] | None = None,
    *,
    dry_run: bool = False,
    redo: bool = False,
    today: str | None = None,
) -> dict[str, Any]:
    """Generate and save news stories for eligible papers; returns a structured report."""
    import psycopg

    today_str = today or date.today().isoformat()
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    report: dict[str, Any] = {"written": [], "skipped": {}}
    with psycopg.connect(url, autocommit=True) as conn, psycopg.connect(url, autocommit=True) as writer:
        row = writer.execute("select writer from app.content_writer").fetchone()
        mode = row[0] if row else None
        if not dry_run and mode != "postgres":
            raise ValueError(f"content writer is {mode!r}, not 'postgres'; nothing was written")
        papers, taken_ids, existing_by_paper = _load_db_state(conn)
        for paper in papers:
            paper_id = paper["id"]
            if only is not None and paper_id not in only:
                continue
            if only is None and not is_newsworthy(paper):
                continue
            if paper_id in existing_by_paper and not redo:
                report["skipped"][paper_id] = "already has news story"
                continue
            sid = resolve_story_id(paper_id, taken_ids, existing_by_paper, redo=redo)
            story, found = draft(client, paper, sid, today_str)
            if dry_run:
                print(json.dumps({"id": sid, "problems": found, "story": story}, ensure_ascii=False, indent=2))
            if found:
                report["skipped"][paper_id] = "; ".join(found)
                continue
            if not dry_run:
                save(story, writer, replace=redo)
            taken_ids.add(sid)
            existing_by_paper[paper_id] = sid
            report["written"].append({"id": sid, "paperId": paper_id})
    return report | {"at": datetime.now(UTC).isoformat(timespec="seconds"), "dryRun": dry_run}


def write_news_for_new(published: list[dict[str, Any]], today: str | None = None) -> None:
    """Paper Watch hook: draft and publish news for top newly auto-published papers (non-fatal)."""
    url = os.environ.get(DATABASE_ENV)
    paper_ids = select_candidates(published)
    if not paper_ids or not url or not ANTHROPIC_API_KEY:
        return
    try:
        report = run(url, only=paper_ids, today=today)
        print(f"  [News] {json.dumps(report, ensure_ascii=False)}")
    except Exception as exc:  # news is optional; the papers are already published
        print(f"  [News] not written: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=os.environ.get(DATABASE_ENV))
    parser.add_argument("--only", nargs="*", help="paper IDs to turn into news stories")
    parser.add_argument("--dry-run", action="store_true", help="print drafted stories without writing")
    parser.add_argument("--redo", action="store_true", help="replace existing news stories for targeted papers")
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error(f"--database-url (or {DATABASE_ENV}) is required")
    if not ANTHROPIC_API_KEY:
        parser.error("ANTHROPIC_API_KEY is required")
    report = run(args.database_url, args.only or None, dry_run=args.dry_run, redo=args.redo)
    print(json.dumps({"job": "news-writer", **report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
