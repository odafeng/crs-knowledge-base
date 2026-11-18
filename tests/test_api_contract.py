"""Provider-neutral API contracts against the actual published content and privacy boundaries."""

import copy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from openapi_spec_validator import validate
from sitegen.config import TOPICS
from sitegen.load import load_kb
from sitegen.urls import paper_path

from validate import KNOWN_STUDY_TYPES

ROOT = Path(__file__).resolve().parent.parent
SPEC = yaml.safe_load((ROOT / "contracts/openapi.yaml").read_text())
RAW = json.loads((ROOT / "data/papers.json").read_text())
KB = load_kb(ROOT / "data/papers.json", ROOT / "data/news.json")


def validator(name):
    return Draft202012Validator(
        {"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]},
        format_checker=FormatChecker(),
    )


def public_paper(paper):
    source = next(p for p in RAW[paper.topic.key]["papers"] if p["id"] == paper.id)
    return {
        **{key: value for key, value in source.items() if key != "file"},
        "slug": paper.slug,
        "topic": paper.topic.key,
        "detailHtml": paper.detail_html,
    }


def test_openapi_is_valid_and_has_unique_operation_ids():
    validate(SPEC)
    ids = [op["operationId"] for path in SPEC["paths"].values() for op in path.values()]
    assert len(ids) == len(set(ids))
    assert set(SPEC["components"]["schemas"]["TopicKey"]["enum"]) == set(RAW)
    assert set(SPEC["components"]["schemas"]["Paper"]["properties"]["studyType"]["enum"]) == KNOWN_STUDY_TYPES


@pytest.mark.parametrize("paper", KB.papers, ids=lambda paper: paper.id)
def test_every_existing_paper_fits_without_changing_ids_or_review_state(paper):
    dto = public_paper(paper)
    validator("Paper").validate(dto)
    assert paper_path(paper) == f"/papers/{dto['slug']}/"
    assert dto["id"] == paper.id
    assert dto["source"] == paper.source
    assert dto["detailHtml"] == paper.detail_html
    for relation in dto["relations"]:
        assert KB.paper(relation["targetId"]) is not None


@pytest.mark.parametrize("status", ["auto", "accepted"])
def test_bot_review_states_do_not_change_the_source_level(status):
    dto = public_paper(KB.papers[0])
    dto.update(source="secondary", review={"status": status, "publishedAt": "2026-11-16"})
    validator("Paper").validate(dto)


def test_existing_news_and_treatment_cards_fit_the_contract():
    for story in json.loads((ROOT / "data/news.json").read_text()):
        validator("News").validate(story)
        assert KB.paper(story["paperId"]) is not None
    for topic in RAW.values():
        for card in topic.get("standard_of_care", {}).get("cards", []):
            validator("SocCard").validate(card)
    for section in KB.robotic:
        raw = RAW["robotic-surgery"]
        validator("RoboticSection").validate(
            {
                "slug": section.page.slug,
                "timeline": raw[section.page.timeline_key],
                "cards": raw[section.page.cards_key],
                "detailHtml": list(section.details),
            }
        )


@pytest.mark.parametrize("topic", TOPICS, ids=lambda topic: topic.key)
def test_topic_response_keeps_treatment_cards_and_counts(topic):
    validator("Topic").validate(
        {
            "key": topic.key,
            "slug": topic.slug,
            "label": topic.label,
            "title": topic.title,
            "paperCount": len(KB.by_topic(topic)),
            "standardOfCare": RAW[topic.key].get("standard_of_care", {}).get("cards", []),
            "roboticSections": [],
        }
    )


@pytest.mark.parametrize(("parameter", "value"), [("Limit", 0), ("Limit", 101), ("Cursor", 123)])
def test_invalid_pagination_inputs_fail(parameter, value):
    check = Draft202012Validator(
        {"$ref": f"#/components/parameters/{parameter}/schema", "components": SPEC["components"]}
    )
    with pytest.raises(ValidationError):
        check.validate(value)


@pytest.fixture
def anonymous_comment():
    return {
        "id": "comment-1",
        "paperId": KB.papers[0].id,
        "body": "請問這個結果適用哪個族群？",
        "anonymous": True,
        "displayName": None,
        "createdAt": "2026-11-16T00:00:00Z",
        "updatedAt": "2026-11-16T00:00:00Z",
        "likeCount": 0,
    }


@pytest.mark.parametrize("field", ["authorId", "user_id", "email", "user_metadata", "review", "likedBy"])
def test_public_comment_rejects_identity_and_research_fields(anonymous_comment, field):
    validator("PublicComment").validate(anonymous_comment)
    with pytest.raises(ValidationError):
        validator("PublicComment").validate({**anonymous_comment, field: "private"})


def test_anonymous_comments_cannot_expose_a_name(anonymous_comment):
    with pytest.raises(ValidationError):
        validator("PublicComment").validate({**anonymous_comment, "displayName": "Author"})
    validator("PublicComment").validate({**anonymous_comment, "anonymous": False, "displayName": "Reader"})
    with pytest.raises(ValidationError):
        validator("PublicComment").validate({**anonymous_comment, "anonymous": False})


def test_comment_requests_cannot_choose_an_author_or_moderation_state():
    request = {"body": "A reader's comment", "anonymous": True}
    validator("CommentCreate").validate(request)
    for field in ("authorId", "status", "review", "isModerator"):
        with pytest.raises(ValidationError):
            validator("CommentCreate").validate({**request, field: "chosen-by-client"})


# Writes that need no sign-in, each on purpose: a push subscription names a browser, never an account (C5 #95).
# POSTs that need no session: a browser push subscription, and a search whose query belongs in the body (H3).
ANONYMOUS_WRITES = {"/push/subscription", "/semantic-search"}


def test_authentication_and_private_response_boundaries_are_explicit():
    for path, methods in SPEC["paths"].items():
        for method, operation in methods.items():
            private = (
                (method != "get" and path not in ANONYMOUS_WRITES)
                or path == "/me"
                or path.startswith(("/me/", "/admin/", "/forum/"))  # the forum is members only, reads included
            )
            assert operation["security"] == ([{"BearerAuth": []}] if private else [])
            assert "503" in operation["responses"]
            if path != "/health":
                assert "422" in operation["responses"]
            if private:
                assert "private, no-store" in operation["description"]
            if path.startswith("/admin/"):
                assert operation["x-required-permission"] == "comments:moderate"


def test_invalid_research_and_unknown_response_fields_fail_validation():
    dto = public_paper(KB.papers[0])
    for field, value in (("source", "unverified"), ("reviewedAt", "yesterday"), ("studyType", "Invented RCT")):
        invalid = copy.deepcopy(dto)
        invalid[field] = value
        with pytest.raises(ValidationError):
            validator("Paper").validate(invalid)
    with pytest.raises(ValidationError):
        validator("Paper").validate({**dto, "private_notes": "internal"})
