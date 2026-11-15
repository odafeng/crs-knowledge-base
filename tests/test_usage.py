"""Tests for per-run usage and cost accounting."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from classify import classify_paper
from usage import UsageLog


def _response(model="claude-fable-5-2", **tokens):
    usage = SimpleNamespace(
        input_tokens=tokens.get("input", 0),
        output_tokens=tokens.get("output", 0),
        cache_creation_input_tokens=tokens.get("write", 0),
        cache_read_input_tokens=tokens.get("read", 0),
    )
    return SimpleNamespace(model=model, usage=usage)


def test_cost_uses_serving_model_and_cache_rates():
    log = UsageLog()
    log.record(_response(input=1_000_000, output=1_000_000, write=1_000_000, read=1_000_000), "x")
    # Fable 5.2: $8 in + $40 out + $10 cache write + $0.20 cache read
    assert log.total_cost() == 58.2


def test_fallback_model_priced_separately():
    log = UsageLog()
    log.record(_response(output=1_000_000), "claude-fable-5-2")
    log.record(_response(model="claude-opus-5", output=1_000_000), "claude-fable-5-2")
    assert set(log.by_model) == {"claude-fable-5-2", "claude-opus-5"}
    assert log.total_cost() == 40 + 25


def test_unknown_model_has_no_total():
    log = UsageLog()
    log.record(_response(model="claude-future-9"), "claude-future-9")
    assert log.total_cost() is None
    assert "no price on file" in log.summary_lines()[0]


def test_writes_github_step_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    log = UsageLog()
    log.record(_response(input=1000, output=100), "claude-fable-5-2")
    log.report()
    assert "Paper Watch API usage" in summary.read_text()


@patch("classify.ANTHROPIC_API_KEY", "test-key")
def test_classifier_requests_prompt_caching_and_records_usage(sample_candidate):
    response = MagicMock()
    response.stop_reason = "tool_use"
    response.model = "claude-fable-5-2"
    response.usage = SimpleNamespace(
        input_tokens=10, output_tokens=5, cache_creation_input_tokens=0, cache_read_input_tokens=0
    )
    block = MagicMock(type="tool_use", input={"relevance_score": 2, "contextual_analysis": "x", "evidence": []})
    block.name = "submit_classification"
    response.content = [block]
    client = MagicMock()
    client.beta.messages.create.return_value = response

    log = UsageLog()
    with patch("classify.USAGE", log):
        classify_paper(client, sample_candidate)
    assert client.beta.messages.create.call_args.kwargs["cache_control"] == {"type": "ephemeral"}
    assert log.by_model["claude-fable-5-2"].requests == 1
