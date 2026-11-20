"""3/5 papers listed in one digest issue for the maintainer to pick from (J6 #218)."""

import json
from unittest.mock import patch

import digest

PAPERS = [
    {"pmid": "1", "topic": "generic-CRS", "title": "OSERO", "journal": "Br J Cancer", "year": 2026,
     "ai_analysis": "前瞻觀察性研究，n=468。"},
    {"pmid": "2", "topic": "mCRC-RAS-wt", "title": "Rechallenge", "journal": "ESMO Open", "year": 2026},
    {"pmid": "3", "topic": "generic-CRS", "title": "Fruquintinib + TAS-102", "journal": "Oncologist", "year": 2026},
]  # fmt: skip


def tick(body: str, *indices: int) -> str:
    for i in indices:
        body = body.replace(f"- [ ] [c{i}]", f"- [x] [c{i}]")
    return body


def test_each_paper_gets_a_checkbox_a_link_and_the_ai_reason():
    body = digest.format_digest_body(PAPERS, "2026-11-20")
    assert "- [ ] [c0] [OSERO](https://pubmed.ncbi.nlm.nih.gov/1/)（Br J Cancer 2026，PMID 1）" in body
    assert "  - AI：前瞻觀察性研究，n=468。" in body
    assert body.index("### `generic-CRS`") < body.index("[c2]") < body.index("### `mCRC-RAS-wt`")
    assert digest.is_digest(body)


def test_ticked_papers_come_back_by_topic():
    body = tick(digest.format_digest_body(PAPERS, "2026-11-20"), 0, 1, 2)
    assert digest.picked(body) == {"generic-CRS": ["1", "3"], "mCRC-RAS-wt": ["2"]}
    assert digest.picked(digest.format_digest_body(PAPERS, "2026-11-20")) == {}


def test_other_issues_are_not_digests():
    assert not digest.is_digest("")
    assert not digest.is_digest(None)
    assert not digest.is_digest("<!-- paper-watch:paper\n{}\n-->")


def test_one_issue_per_run_and_papers_without_a_pmid_are_left_out():
    with patch("digest.run_gh", return_value=(True, "url")) as gh, patch("digest.ensure_labels"):
        digest.create_digest_issue([*PAPERS, {"title": "abstract only", "topic": "generic-CRS"}], "2026-11-20")
    (args,) = gh.call_args.args
    assert args[args.index("--title") + 1] == "[待挑選] 3 篇 3 分論文（2026-11-20）"
    assert args[args.index("--label") + 1] == "paper-digest"
    assert "abstract only" not in args[args.index("--body") + 1]


def test_nothing_to_list_opens_nothing():
    with patch("digest.run_gh") as gh:
        digest.create_digest_issue([{"title": "abstract only"}], "2026-11-20")
        digest.create_digest_issue(PAPERS, "2026-11-20", dry_run=True)
    gh.assert_not_called()


def test_only_digests_the_pipeline_opened_are_taken():
    listed = [
        {"number": 9, "body": "b", "author": {"login": "owner"}},
        {"number": 4, "body": "b", "author": {"login": "app/github-actions"}},
        {"number": 5, "body": "b", "author": {"login": "someone"}},
    ]
    with patch("digest.run_gh", return_value=(True, json.dumps(listed))), patch("digest.GITHUB_REPO", "owner/repo"):
        assert [i["number"] for i in digest.accepted_digests()] == [4, 9]
    with patch("digest.run_gh", return_value=(False, "")):
        assert digest.accepted_digests() is None


def test_finish_closes_the_digest_or_asks_again():
    with patch("digest.run_gh") as gh:
        digest.finish(7, 2, 2)
    calls = [c.args[0] for c in gh.call_args_list]
    assert calls[-1] == ["issue", "close", "7", "--reason", "completed"]
    assert "開出 2 張審核 issue" in calls[0][-1]

    with patch("digest.run_gh") as gh:
        digest.finish(7, 0, 0)
    calls = [c.args[0] for c in gh.call_args_list]
    assert calls[-1] == ["issue", "edit", "7", "--remove-label", "accepted"]
    assert not any(c[:2] == ["issue", "close"] for c in calls)
