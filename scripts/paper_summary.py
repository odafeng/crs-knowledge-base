"""Chinese at-a-glance summaries for papers (I2 #191, ADR-0025).

python scripts/paper_summary.py [--database-url URL] [--only ID ...] [--dry-run] [--redo]

A reader landing on a paper page should see in seconds what the study asked, in whom, against what, what it found
and what to be careful about. For each paper with a DOI this reads its PubMed abstract, asks Claude for that summary
in Traditional Chinese, and keeps it only if every number in it appears in the abstract or in the paper's existing
entry (the rule of the auto-publish gate, ADR-0013) and it has the shape scripts/validate.py checks. A kept summary
is written through the content writer, unreviewed until the maintainer marks the paper reviewed. Taiwan approval
and reimbursement are not written here: the page shows the topic's checked regulatory rows instead.
"""

import argparse
import json
import os
import re
import sys
from datetime import UTC, date, datetime
from typing import Any

from anthropic import Anthropic

from config import ANTHROPIC_API_KEY, CLASSIFY_MODEL, FALLBACK_BETA
from content_store import DATABASE_ENV, content_session
from fetch_pubmed import efetch, esearch
from usage import USAGE
from validate import SUMMARY_LISTS, SUMMARY_TEXT, validate_summary

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "40 字以內：試驗名稱（若有）加上族群與比較，例如「BREAKWATER：BRAF V600E 轉移性大腸癌一線 EC + mFOLFOX6」"},
        "takeaway": {"type": "string", "description": "40 字以內的一句白話結論，帶最重要的一個數字，例如「一線 EC + mFOLFOX6 讓中位存活從 15.1 延長到 30.3 個月」"},
        "question": {"type": "string", "description": "這篇研究想回答的臨床問題，一句"},
        "population": {"type": "string", "description": "收了哪些病人、幾位"},
        "comparison": {"type": "string", "description": "研究設計，以及治療組與對照組各是什麼；單臂研究就寫單臂與治療內容"},
        "findings": {"type": "array", "items": {"type": "string"}, "description": "2 到 4 點主要結果，主要指標放第一點；每點一句、說清楚是哪一組哪個指標；次要或探索性的細節不必列"},
        "meaning": {"type": "string", "description": "這個結果對臨床的意義，一到兩句，不給個別病人的治療建議"},
        "limits": {"type": "array", "items": {"type": "string"}, "description": "1 到 3 點最重要的限制，例如單臂、追蹤短、open-label、期中分析"},
    },
    "required": ["title", "takeaway", "question", "population", "comparison", "findings", "meaning", "limits"],
    "additionalProperties": False,
}  # fmt: skip

SYSTEM = """你替一個給台灣大腸直腸外科醫師看的實證網站，寫單篇文獻的中文速覽。讀者是外科醫師，點進文獻頁時要在幾秒內看懂：這篇在問什麼、收了誰、比什麼、結果如何、代表什麼、要小心什麼。

只用使用者提供的摘要與既有條目，不加入其他來源的知識。數字一律照抄原文，不換算、不四捨五入，也不寫原文沒有的數字；摘要沒寫但既有條目有的數字（例如收案數）可以直接用，不必說明出處。藥名、試驗名、指標縮寫（mOS、HR、pCR 等）保留英文。用台灣的用語，句子短、直接，不寫宣傳語氣，也不寫「摘要未提及」這類說明。"""

# Lancet prints decimals with a middle dot; the site writes a full stop.
_MIDDLE_DOT = re.compile(r"(?<=\d)·(?=\d)")


def numbers(text: str) -> set[str]:
    """Numbers as written, so 30.3 and 0.49 match only themselves."""
    return set(re.findall(r"\d+(?:\.\d+)?", _MIDDLE_DOT.sub(".", text)))


def texts(summary: dict[str, Any]) -> list[str]:
    return [summary[k] for k in SUMMARY_TEXT] + [item for k in SUMMARY_LISTS for item in summary[k]]


def problems(summary: dict[str, Any], sources: str) -> list[str]:
    """Why a summary cannot be kept: the shape validate.py checks, or a number found in neither source."""
    found = validate_summary("summary", summary)
    if found:
        return found
    allowed = numbers(sources)
    if missing := sorted({n for t in texts(summary) for n in numbers(t)} - allowed):
        found.append(f"numbers not in the sources: {', '.join(missing)}")
    return found


def abstract_for(doi: str) -> str:
    pmids = esearch(f'"{doi}"[doi]', reldate=365 * 80)
    articles = efetch(pmids[:1])
    return articles[0].get("abstract", "") if articles else ""


def entry_text(paper: dict[str, Any]) -> str:
    keys = ("regimen", "studyType", "n", "endpoint", "result", "bottomLine", "journal", "year")
    return "\n".join(f"{k}: {paper[k]}" for k in keys if paper.get(k) is not None)


def write(client: Anthropic, paper: dict[str, Any], abstract: str) -> dict[str, Any]:
    prompt = f"<abstract>\n{abstract}\n</abstract>\n\n<entry>\n{entry_text(paper)}\n</entry>\n\n請寫這篇的中文速覽。"
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
    clean = {k: _MIDDLE_DOT.sub(".", v.strip()) for k, v in raw.items() if k in SUMMARY_TEXT}
    clean |= {k: [_MIDDLE_DOT.sub(".", i.strip()) for i in raw[k]] for k in SUMMARY_LISTS}
    return clean | {"model": response.model, "writtenAt": date.today().isoformat(), "reviewedAt": None}


def save(paper_id: str, summary: dict[str, Any], conn: Any = None) -> None:
    """Store one summary through the content writer, so a later Paper Watch run exports and keeps it."""
    with content_session("summarize", paper_id, conn=conn) as session:
        if session.done is not None:
            return
        kb = session.kb
        assert kb is not None, "summaries are written to the database"
        data = kb.load()
        paper = next((p for t in data.values() for p in t.get("papers", []) if p["id"] == paper_id), None)
        if paper is None:
            raise ValueError(f"paper {paper_id} is gone")
        paper["summary"] = summary
        kb.save(data)
        session.record(f"summary {paper_id}")


def papers(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        "select id, doi, regimen, study_type, n, endpoint, result, bottom_line, journal, year, summary"
        " from app.papers where withdrawn_at is null order by id"
    ).fetchall()
    names = {"study_type": "studyType", "bottom_line": "bottomLine"}
    return [{names.get(str(k), str(k)): v for k, v in row.items()} for row in rows]


def run(url: str, only: list[str] | None = None, dry_run: bool = False, redo: bool = False) -> dict[str, Any]:
    """Summarise the papers that lack one (or `only` these); returns what was written and why others were not."""
    import psycopg
    from psycopg.rows import dict_row

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    report: dict[str, Any] = {"written": [], "skipped": {}}
    # Reads use dict rows; the content writer gets its own plain connection, as Paper Watch's does.
    with (
        psycopg.connect(url, row_factory=dict_row, autocommit=True) as conn,
        psycopg.connect(url, autocommit=True) as writer,
    ):
        for paper in papers(conn):
            if only is not None and paper["id"] not in only:
                continue
            if paper["summary"] and not redo:
                continue
            if not paper["doi"]:
                report["skipped"][paper["id"]] = "no DOI"
                continue
            abstract = abstract_for(paper["doi"])
            if not abstract:
                report["skipped"][paper["id"]] = "no abstract on PubMed"
                continue
            summary = write(client, paper, abstract)
            found = problems(summary, abstract + "\n" + entry_text(paper))
            if dry_run:  # every summary, kept or not, so the wording can be judged
                print(json.dumps({"id": paper["id"], "problems": found, **summary}, ensure_ascii=False, indent=2))
            if found:
                report["skipped"][paper["id"]] = "; ".join(found)
                continue
            if not dry_run:
                save(paper["id"], summary, writer)
            report["written"].append(paper["id"])
    return report | {"at": datetime.now(UTC).isoformat(timespec="seconds"), "dryRun": dry_run}


def summarize_new(paper_ids: list[str]) -> None:
    """Paper Watch, after publishing: summarise the new papers. A failure is reported, never fatal to the run."""
    url = os.environ.get(DATABASE_ENV)
    if not paper_ids or not url or not ANTHROPIC_API_KEY:
        return
    try:
        report = run(url, only=paper_ids)
        print(f"  [Summary] {json.dumps(report, ensure_ascii=False)}")
    except Exception as exc:  # a summary is optional; the papers are already published
        print(f"  [Summary] not written: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=os.environ.get(DATABASE_ENV))
    parser.add_argument("--only", nargs="*", help="paper IDs to summarise")
    parser.add_argument("--dry-run", action="store_true", help="print every summary, write nothing")
    parser.add_argument("--redo", action="store_true", help="also rewrite papers that already have a summary")
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error(f"--database-url (or {DATABASE_ENV}) is required")
    if not ANTHROPIC_API_KEY:
        parser.error("ANTHROPIC_API_KEY is required")
    report = run(args.database_url, args.only or None, args.dry_run, args.redo)
    print(json.dumps({"job": "paper-summary", **report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
