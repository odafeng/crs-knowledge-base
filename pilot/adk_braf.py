"""ADK pilot for one topic (E5 #90, ADR-0018): the current classifier against the same agent on Google ADK.

Both arms read one frozen batch of real PubMed candidates for mCRC-BRAF-V600E, use the same model, system prompt,
paper prompt, tools, adaptive thinking and effort, and their output goes through the same provenance gate. The only
setting ADK cannot pass is the server-side `fallbacks` beta; the report says so, and a refusal counts as manual
intervention in either arm. Nothing here writes content or tracking, and nothing is scheduled.

    python pilot/adk_braf.py freeze  --out pilot-out            # PubMed only, no model calls
    python pilot/adk_braf.py run     --out pilot-out --budget-usd 20 [--limit N] [--arms current,adk]
    python pilot/adk_braf.py report  --out pilot-out            # rebuild report.md from results.jsonl

`run` spends money. It stops before a paper whose estimated cost would take the total over --budget-usd (both arms
share it), and resumes where it stopped: papers already in results.jsonl are not run again. The frozen batch holds
abstracts, so --out must stay out of the repository (pilot-out/ is gitignored).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from agent_tools import AGENT_TOOLS, execute_tool  # noqa: E402
from classify import (  # noqa: E402
    FORCE_SUBMIT_PROMPT,
    MAX_AGENT_TURNS,
    MAX_OUTPUT_TOKENS,
    SUBMIT_CLASSIFICATION_TOOL,
    _apply_submission,
    _build_batch_context,
)
from config import CLASSIFY_EFFORT, CLASSIFY_MODEL, load_queries  # noqa: E402
from provenance import evaluate_paper_gate  # noqa: E402
from publish import AUTO_PUBLISH_TOPICS  # noqa: E402
from topic_agents import build_paper_prompt, build_system_prompt  # noqa: E402
from usage import USAGE, ModelUsage  # noqa: E402

TOPIC = "mCRC-BRAF-V600E"
RELDATE = 120
ARMS = ("current", "adk")
# Before any paper has run, assume this much per paper and arm (USD); the 2026-11-19 catch-up averaged about 0.06.
FIRST_ESTIMATE = 0.15
# Exit thresholds written before the run (posted on #90): ADK may cost or take at most this many times the current.
MAX_RATIO = 1.5


@dataclass
class ArmResult:
    arm: str
    pmid: str
    score: int | None = None
    has_entry: bool = False
    parse_failed: bool = False
    gate_passed: bool = False
    gate_reasons: list[str] = field(default_factory=list)
    tool_calls: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    error: str | None = None


def _batch(paper: dict, candidates: list[dict]) -> str:
    return _build_batch_context(paper, candidates) if len(candidates) > 1 else ""


def _gate(arm: ArmResult, paper: dict) -> ArmResult:
    arm.score = paper.get("ai_score")
    arm.parse_failed = bool(paper.get("ai_parse_failed"))
    arm.has_entry = bool(paper.get("ai_suggested_js"))
    gate = evaluate_paper_gate(paper, AUTO_PUBLISH_TOPICS)
    arm.gate_passed = not gate.reasons and arm.has_entry
    arm.gate_reasons = list(gate.reasons)
    return arm


def _price(usage: ModelUsage) -> float:
    return usage.cost(CLASSIFY_MODEL) or 0.0


# --- the current classifier ------------------------------------------------------------------------------------


def run_current(paper: dict, candidates: list[dict], client: Any) -> ArmResult:
    """The production classify_paper, unchanged; its usage is the difference in the shared USAGE log."""
    import classify

    result = ArmResult("current", paper["pmid"])
    before = {m: asdict(u) for m, u in USAGE.by_model.items()}
    calls = 0
    original = classify.execute_tool

    def counting(name: str, args: dict) -> str:
        nonlocal calls
        calls += 1
        return original(name, args)

    classify.execute_tool = counting
    started = time.perf_counter()
    try:
        classified = classify.classify_paper(client, dict(paper), candidates)
    except Exception as exc:  # one paper's failure must not end the pilot; it is counted as intervention
        result.error = repr(exc)[:300]
        classified = {**paper, "ai_parse_failed": True}
    finally:
        classify.execute_tool = original
    result.seconds = time.perf_counter() - started
    result.tool_calls = calls
    for model, u in USAGE.by_model.items():
        prior = before.get(model, asdict(ModelUsage()))
        delta = ModelUsage(**{k: v - prior[k] for k, v in asdict(u).items()})
        result.input_tokens += delta.input_tokens
        result.output_tokens += delta.output_tokens
        result.cache_write_tokens += delta.cache_write_tokens
        result.cache_read_tokens += delta.cache_read_tokens
        result.cost_usd += delta.cost(model) or 0.0
    return _gate(result, classified)


# --- the same agent on ADK -------------------------------------------------------------------------------------


def build_adk_agent(model: Any, holder: dict) -> Any:
    """An LlmAgent with the current tools and a submit tool that ends the run. `holder` receives the submission."""
    from google.adk.agents import LlmAgent
    from google.adk.models.anthropic_llm import AnthropicGenerateContentConfig
    from google.adk.tools.base_tool import BaseTool
    from google.genai import types

    class SchemaTool(BaseTool):
        def __init__(self, spec: dict, run: Callable[[dict, Any], Any]) -> None:
            super().__init__(name=spec["name"], description=spec["description"])
            self._schema = spec["input_schema"]
            self._run = run

        def _get_declaration(self) -> types.FunctionDeclaration:
            return types.FunctionDeclaration(
                name=self.name, description=self.description, parameters_json_schema=self._schema
            )

        async def run_async(self, *, args: dict[str, Any], tool_context: Any) -> Any:
            return await self._run(args, tool_context)

    def research(name: str) -> Callable[[dict, Any], Any]:
        async def run(args: dict, _context: Any) -> dict:
            holder["tool_calls"] = holder.get("tool_calls", 0) + 1
            return {"result": await asyncio.to_thread(execute_tool, name, args)}

        return run

    async def submit(args: dict, context: Any) -> dict:
        holder["submission"] = args
        context.actions.skip_summarization = True  # the submission is the answer; no further model turn
        return {"result": "recorded"}

    tools = [SchemaTool(spec, research(spec["name"])) for spec in AGENT_TOOLS]
    tools.append(SchemaTool(SUBMIT_CLASSIFICATION_TOOL, submit))
    return LlmAgent(
        name="braf_classifier",
        model=model,
        instruction=holder["system_prompt"],
        tools=tools,
        generate_content_config=AnthropicGenerateContentConfig(
            effort=CLASSIFY_EFFORT,
            thinking_config=types.ThinkingConfig(thinking_budget=-1),  # -1: adaptive, as the current arm
        ),
    )


async def run_adk(paper: dict, candidates: list[dict], model: Any) -> ArmResult:
    """One session per paper, like the current arm's one conversation per paper; one nudge if it ends unsubmitted."""
    from google.adk.agents.context_cache_config import ContextCacheConfig
    from google.adk.agents.run_config import RunConfig
    from google.adk.apps.app import App
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    result = ArmResult("adk", paper["pmid"])
    holder: dict[str, Any] = {"system_prompt": build_system_prompt(paper.get("topic", ""))}
    app = App(
        name="adk_pilot",
        root_agent=build_adk_agent(model, holder),
        context_cache_config=ContextCacheConfig(min_tokens=0),
    )
    sessions = InMemorySessionService()
    runner = Runner(app=app, session_service=sessions)
    session = await sessions.create_session(app_name="adk_pilot", user_id="pilot")
    usage = ModelUsage()
    started = time.perf_counter()
    try:
        for text in (build_paper_prompt(paper) + _batch(paper, candidates), FORCE_SUBMIT_PROMPT):
            message = types.Content(role="user", parts=[types.Part(text=text)])
            async for event in runner.run_async(
                user_id="pilot",
                session_id=session.id,
                new_message=message,
                run_config=RunConfig(max_llm_calls=MAX_AGENT_TURNS + 1),
            ):
                _add_usage(usage, event)
                if event.error_code and not result.error:
                    result.error = f"{event.error_code}: {event.error_message}"[:300]
            if "submission" in holder:
                break
    except Exception as exc:  # e.g. the call limit; counted as intervention like a parse failure
        result.error = repr(exc)[:300]
    result.seconds = time.perf_counter() - started
    result.tool_calls = holder.get("tool_calls", 0)
    result.input_tokens, result.output_tokens = usage.input_tokens, usage.output_tokens
    result.cache_write_tokens, result.cache_read_tokens = usage.cache_write_tokens, usage.cache_read_tokens
    result.cost_usd = _price(usage)
    submission = holder.get("submission")
    classified = _apply_submission(dict(paper), submission) if submission else {**paper, "ai_parse_failed": True}
    return _gate(result, classified)


def _add_usage(usage: ModelUsage, event: Any) -> None:
    """ADK reports prompt tokens as uncached + cache read + cache write, and output without thinking."""
    meta = getattr(event, "usage_metadata", None)
    if meta is None or getattr(event, "partial", False):
        return
    read = meta.cached_content_token_count or 0
    write = getattr(event, "cache_creation_token_count", None) or 0
    usage.requests += 1
    usage.input_tokens += max((meta.prompt_token_count or 0) - read - write, 0)
    usage.cache_read_tokens += read
    usage.cache_write_tokens += write
    usage.output_tokens += (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)


# --- the run ---------------------------------------------------------------------------------------------------


@dataclass
class Budget:
    cap: float
    spent: float = 0.0
    runs: int = 0

    def estimate(self) -> float:
        """The next arm-paper's likely cost: the average so far, never below a quarter of the first guess."""
        return max(self.spent / self.runs, FIRST_ESTIMATE / 4) if self.runs else FIRST_ESTIMATE

    def allows(self, arms: int) -> bool:
        return self.spent + arms * self.estimate() <= self.cap

    def add(self, cost: float) -> None:
        self.spent += cost
        self.runs += 1


def freeze(out: Path, reldate: int = RELDATE) -> list[dict]:
    """The BRAF query's PubMed results for the window, tracked or not, written once and read by every run."""
    from fetch_pubmed import efetch, esearch

    pmids = esearch(load_queries()[TOPIC]["pubmed_query"], reldate=reldate)
    candidates = [{**art, "topic": TOPIC} for art in efetch(pmids)] if pmids else []
    out.mkdir(parents=True, exist_ok=True)
    (out / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=1))
    return candidates


def load_results(out: Path) -> list[dict]:
    path = out / "results.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def run(
    out: Path,
    budget_usd: float,
    arms: tuple[str, ...] = ARMS,
    limit: int | None = None,
    runners: dict[str, Callable[[dict, list[dict]], ArmResult]] | None = None,
) -> dict[str, Any]:
    """Run each paper through every arm, alternating which arm goes first so neither always meets a warm cache."""
    candidates = json.loads((out / "candidates.json").read_text())
    done = load_results(out)
    finished = {(r["arm"], r["pmid"]) for r in done}
    budget = Budget(budget_usd)
    for r in done:
        budget.add(r["cost_usd"])
    runners = runners or _live_runners()
    stopped = None
    with (out / "results.jsonl").open("a") as sink:
        for i, paper in enumerate(candidates[:limit]):
            order = arms if i % 2 == 0 else tuple(reversed(arms))
            todo = [arm for arm in order if (arm, paper["pmid"]) not in finished]
            if not todo:
                continue
            if not budget.allows(len(todo)):
                stopped = f"budget: spent {budget.spent:.2f} of {budget.cap:.2f} USD before paper {i + 1}"
                break
            for arm in todo:
                result = runners[arm](paper, candidates)
                budget.add(result.cost_usd)
                sink.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
                sink.flush()
    write_report(out, stopped)
    return {"spent_usd": round(budget.spent, 4), "stopped": stopped}


def _live_runners() -> dict[str, Callable[[dict, list[dict]], ArmResult]]:
    from anthropic import Anthropic, AsyncAnthropic
    from google.adk.models.anthropic_llm import AnthropicLlm

    from config import ANTHROPIC_API_KEY

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    model = AnthropicLlm(
        model=CLASSIFY_MODEL, max_tokens=MAX_OUTPUT_TOKENS, client=AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    )
    return {
        "current": lambda paper, batch: run_current(paper, batch, client),
        "adk": lambda paper, batch: asyncio.run(run_adk(paper, batch, model)),
    }


# --- the report ------------------------------------------------------------------------------------------------


def verdict(results: list[dict]) -> tuple[bool, list[str]]:
    """Apply the exit conditions posted on #90 before the run. True means none was hit (not yet a reason to switch)."""
    by_pmid: dict[str, dict[str, dict]] = {}
    for r in results:
        by_pmid.setdefault(r["pmid"], {})[r["arm"]] = r
    pairs = [arms for arms in by_pmid.values() if {"current", "adk"} <= arms.keys()]
    reasons = []
    worse = [a["current"]["pmid"] for a in pairs if a["current"]["gate_passed"] and not a["adk"]["gate_passed"]]
    if worse:
        reasons.append(f"ADK 未通過 gate、現行版通過的論文：{', '.join(worse)}")
    total = {arm: sum(a[arm]["cost_usd"] for a in pairs) for arm in ARMS}
    secs = {arm: sum(a[arm]["seconds"] for a in pairs) for arm in ARMS}
    if total["current"] and total["adk"] > MAX_RATIO * total["current"]:
        reasons.append(f"ADK 費用為現行版的 {total['adk'] / total['current']:.2f} 倍（上限 {MAX_RATIO}）")
    if secs["current"] and secs["adk"] > MAX_RATIO * secs["current"]:
        reasons.append(f"ADK 耗時為現行版的 {secs['adk'] / secs['current']:.2f} 倍（上限 {MAX_RATIO}）")
    needs = {arm: sum(1 for a in pairs if a[arm]["parse_failed"] or a[arm]["error"]) for arm in ARMS}
    if needs["adk"] > needs["current"]:
        reasons.append(f"ADK 需要人工介入 {needs['adk']} 篇，現行版 {needs['current']} 篇")
    return not reasons, reasons


def write_report(out: Path, stopped: str | None = None) -> Path:
    results = load_results(out)
    ok, reasons = verdict(results)
    rows = ["| PMID | 現行：分數／gate | ADK：分數／gate | 現行 USD／秒 | ADK USD／秒 |", "|---|---|---|---|---|"]
    by_pmid: dict[str, dict[str, dict]] = {}
    for r in results:
        by_pmid.setdefault(r["pmid"], {})[r["arm"]] = r

    def cell(r: dict | None, kind: str) -> str:
        if r is None:
            return "—"
        if kind == "gate":
            state = "通過" if r["gate_passed"] else ("parse failure" if r["parse_failed"] else "不通過")
            return f"{r['score']}／{state}"
        return f"{r['cost_usd']:.3f}／{r['seconds']:.0f}"

    for pmid, arms in by_pmid.items():
        rows.append(
            f"| {pmid} | {cell(arms.get('current'), 'gate')} | {cell(arms.get('adk'), 'gate')} | "
            f"{cell(arms.get('current'), 'cost')} | {cell(arms.get('adk'), 'cost')} |"
        )
    total = sum(r["cost_usd"] for r in results)
    lines = [
        f"# ADK pilot：{TOPIC}",
        "",
        f"論文 {len(by_pmid)} 篇，總花費 USD {total:.2f}。" + (f"提前停止：{stopped}。" if stopped else ""),
        "設定差異：ADK 不支援 server-side `fallbacks` beta，模型拒答時沒有備援；兩邊的拒答都算人工介入。",
        "",
        "## 退出條件",
        "沒有觸發任何退出條件；是否改用 ADK 仍需具體的好處。"
        if ok
        else "觸發：\n" + "\n".join(f"- {r}" for r in reasons),
        "",
        "## 逐篇",
        *rows,
    ]
    path = out / "report.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["freeze", "run", "report"])
    parser.add_argument("--out", type=Path, default=ROOT / "pilot-out")
    parser.add_argument("--budget-usd", type=float, default=20.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--reldate", type=int, default=RELDATE)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        print(f"froze {len(freeze(args.out, args.reldate))} candidates into {args.out / 'candidates.json'}")
    elif args.command == "run":
        arms = tuple(a for a in args.arms.split(",") if a in ARMS)
        print(json.dumps(run(args.out, args.budget_usd, arms, args.limit), ensure_ascii=False))
    else:
        print(write_report(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
