"""The ADK pilot's wiring (E5 #90) with fake models: no model is called, no money is spent, no network is used."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("google.adk")

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pilot"))
import adk_braf
from adk_braf import ArmResult, Budget, run, run_adk, run_current, verdict, write_report

FULL_ABSTRACT = (
    "BACKGROUND: Synthetic. METHODS: In this phase 3 trial, 300 patients were randomised. "
    "RESULTS: Median overall survival was 30.3 months versus 15.1 months. CONCLUSIONS: Synthetic data."
)
PAPER = {
    "pmid": "99990001", "doi": "10.9999/pilot", "title": "Synthetic phase 3 trial", "journal": "Test Journal",
    "year": "2026", "topic": "mCRC-BRAF-V600E", "abstract": FULL_ABSTRACT, "source": "pubmed",
}  # fmt: skip
SUBMISSION = {"relevance_score": 3, "contextual_analysis": "合成測試資料。", "evidence": []}


class FakeClaude(BaseLlm):
    """Answers the first turn with a research tool call and the next with the submission; records each request."""

    model: str = "fake-claude"
    requests: list[Any] = Field(default_factory=list)

    async def generate_content_async(self, llm_request: Any, stream: bool = False):  # type: ignore[override]
        self.requests.append(llm_request)
        first = len(self.requests) == 1
        call = (
            types.FunctionCall(name="lookup_existing_papers", args={"topic": "mCRC-BRAF-V600E"})
            if first
            else types.FunctionCall(name="submit_classification", args=SUBMISSION)
        )
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(function_call=call)]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=1000,
                cached_content_token_count=600,
                candidates_token_count=100,
                thoughts_token_count=50,
            ),  # fmt: skip
            cache_creation_token_count=200,
        )


@pytest.fixture(autouse=True)
def no_research_network(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    def fake(name: str, args: dict) -> str:
        calls.append((name, args))
        return "[]"

    monkeypatch.setattr(adk_braf, "execute_tool", fake)
    import classify

    monkeypatch.setattr(classify, "execute_tool", fake)
    return calls


def test_the_adk_arm_uses_the_same_prompt_and_tools_and_stops_at_the_submission(no_research_network: list) -> None:
    model = FakeClaude(requests=[])
    result = asyncio.run(run_adk(dict(PAPER), [PAPER], model))
    assert result.error is None and not result.parse_failed and result.score == 3
    # Two model turns: research, then submit. The submission ends the run without a summarising turn.
    assert len(model.requests) == 2
    assert no_research_network == [("lookup_existing_papers", {"topic": "mCRC-BRAF-V600E"})]
    assert result.tool_calls == 1
    request = model.requests[0]
    declared = {d.name for tool in request.config.tools for d in tool.function_declarations}
    assert declared == {t["name"] for t in adk_braf.AGENT_TOOLS} | {"submit_classification"}
    assert adk_braf.build_system_prompt("mCRC-BRAF-V600E") in str(request.config.system_instruction)
    assert "Synthetic phase 3 trial" in str(request.contents[0])
    assert request.config.thinking_config.thinking_budget == -1 and request.config.effort == adk_braf.CLASSIFY_EFFORT
    # Usage per turn: prompt 1000 = 200 uncached + 600 read + 200 written; output 100 + 50 thinking.
    assert (result.input_tokens, result.cache_read_tokens, result.cache_write_tokens, result.output_tokens) == (
        400, 1200, 400, 300,
    )  # fmt: skip
    assert result.cost_usd > 0


def test_the_current_arm_is_the_production_classifier() -> None:
    client = MagicMock()
    research, submit = MagicMock(), MagicMock()
    research.stop_reason = submit.stop_reason = "tool_use"
    research.content = [MagicMock(type="tool_use", input={"topic": "mCRC-BRAF-V600E"}, id="t1")]
    research.content[0].name = "lookup_existing_papers"
    submit.content = [MagicMock(type="tool_use", input=SUBMISSION, id="s1")]
    submit.content[0].name = "submit_classification"
    client.beta.messages.create.side_effect = [research, submit]
    result = run_current(dict(PAPER), [PAPER], client)
    assert result.score == 3 and result.tool_calls == 1 and not result.parse_failed
    assert not result.gate_passed  # a score of 3 gives no entry to publish


def fake_runners(costs: dict[str, float], log: list[tuple[str, str]], gate: dict[str, bool] | None = None):
    def runner(arm: str):
        def go(paper: dict, _batch: list[dict]) -> ArmResult:
            log.append((arm, paper["pmid"]))
            passed = (gate or {}).get(arm, True)
            return ArmResult(arm, paper["pmid"], score=4, has_entry=True, gate_passed=passed, cost_usd=costs[arm],
                             seconds=10.0)  # fmt: skip

        return go

    return {arm: runner(arm) for arm in adk_braf.ARMS}


def frozen(tmp_path: Path, n: int) -> Path:
    (tmp_path / "candidates.json").write_text(json.dumps([{**PAPER, "pmid": str(i)} for i in range(n)]))
    return tmp_path


def test_the_budget_stops_before_a_paper_would_exceed_it_and_a_rerun_resumes(tmp_path: Path) -> None:
    out, log = frozen(tmp_path, 10), []
    first = run(out, 1.0, runners=fake_runners({"current": 0.2, "adk": 0.2}, log))
    # 0.15 per arm is assumed for the first paper, then the real 0.2: two papers (0.8), the third would pass 1.0.
    assert first["spent_usd"] == pytest.approx(0.8) and "budget" in first["stopped"]
    assert len(log) == 4
    # Alternating order: neither arm always runs first.
    assert [arm for arm, _ in log] == ["current", "adk", "adk", "current"]
    again = run(out, 2.0, runners=fake_runners({"current": 0.2, "adk": 0.2}, log))
    assert again["spent_usd"] == pytest.approx(2.0) and len(log) == 10  # papers 0 and 1 were not run again
    assert Budget(5.0).estimate() == adk_braf.FIRST_ESTIMATE


def test_exit_conditions(tmp_path: Path) -> None:
    out, log = frozen(tmp_path, 2), []
    run(out, 20.0, runners=fake_runners({"current": 0.1, "adk": 0.1}, log))
    assert verdict(adk_braf.load_results(out)) == (True, [])
    worse = [r | {"gate_passed": False} if r["arm"] == "adk" else r for r in adk_braf.load_results(out)]
    ok, reasons = verdict(worse)
    assert not ok and "ADK 未通過 gate" in reasons[0]
    costly = [r | {"cost_usd": 0.2} if r["arm"] == "adk" else r for r in adk_braf.load_results(out)]
    assert any("費用為現行版的 2.00 倍" in r for r in verdict(costly)[1])
    failing = [r | {"parse_failed": True} if r["arm"] == "adk" else r for r in adk_braf.load_results(out)]
    assert any("人工介入 2 篇" in r for r in verdict(failing)[1])


def test_the_report_names_the_setting_difference_and_the_outcome(tmp_path: Path) -> None:
    out, log = frozen(tmp_path, 1), []
    run(out, 20.0, runners=fake_runners({"current": 0.1, "adk": 0.1}, log, gate={"adk": False}))
    report = write_report(out).read_text()
    assert "fallbacks" in report and "觸發" in report and "| 0 | 4／通過 | 4／不通過 |" in report
