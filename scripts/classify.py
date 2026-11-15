"""Layer 2: Topic-specific AI agents with tool use for paper classification.

Each agent runs in an agentic loop with research tools AND a mandatory
submit_classification tool that forces structured JSON output.
No more fragile regex-based JSON extraction from free-form text.
"""

import json
import sys

from anthropic import Anthropic

from agent_tools import AGENT_TOOLS, execute_tool
from config import ANTHROPIC_API_KEY, CLASSIFY_EFFORT, CLASSIFY_MODEL, FALLBACK_BETA, RELEVANCE_THRESHOLD
from topic_agents import build_paper_prompt, build_system_prompt
from usage import USAGE

MAX_AGENT_TURNS = 8  # Max tool-use rounds per paper
MAX_OUTPUT_TOKENS = 16000  # Thinking is always on and counts toward max_tokens

# Nudge sent when the agent runs out of turns (or stops) without submitting.
FORCE_SUBMIT_PROMPT = (
    "你已經用完可使用的研究回合。請立即根據目前已掌握的資訊呼叫 submit_classification 工具"
    "提交最終分類。若資訊仍不完整（例如摘要缺失），請據此保守評分，"
    "並在 contextual_analysis 中說明資訊限制。"
)

# Last-resort prompt for the structured-output call (tools disabled).
RESCUE_PROMPT = (
    "研究回合已全部用完，不能再呼叫任何工具。請直接依目前已掌握的資訊輸出最終分類 JSON。"
    "資訊不完整時保守評分，並在 contextual_analysis 中說明資訊限制。"
)

EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string", "description": "含該數字的片段，例如 'mOS 30.3 vs 15.1 mo'"},
        "source": {"type": "string", "enum": ["abstract", "web_fetch", "inference"]},
        "quote": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "abstract / web_fetch：原文逐字片段（直接複製，不可改寫或翻譯）。inference：null",
        },
        "url": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "web_fetch：讀到該數字的網址。其他：null",
        },
    },
    "required": ["claim", "source", "quote", "url"],
    "additionalProperties": False,
}

RELATION_SCHEMA = {
    "type": "object",
    "properties": {
        "targetId": {"type": "string"},
        "type": {
            "type": "string",
            "enum": ["builds_on", "supersedes", "subgroup_of", "same_regimen", "contradicts"],
        },
    },
    "required": ["targetId", "type"],
    "additionalProperties": False,
}

# The submit_classification tool forces the agent to output structured JSON.
# This eliminates the fragile "parse JSON from free text" problem.
SUBMIT_CLASSIFICATION_TOOL = {
    "name": "submit_classification",
    "description": (
        "Submit your final classification for the candidate paper. "
        "You MUST call this tool exactly once as your final action. "
        "Do not write the classification as plain text — always use this tool."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "relevance_score": {
                "type": "integer",
                "description": "1-5 relevance score",
                "enum": [1, 2, 3, 4, 5],
            },
            "contextual_analysis": {
                "type": "string",
                "description": "繁體中文 contextual analysis (150-200 chars)",
            },
            "bottom_line": {
                "type": "string",
                "description": "繁體中文 one-line summary (≤100 chars). Required for score ≥ 4.",
            },
            "suggested_js": {
                "type": "object",
                "description": "JS paper object draft. Required for score ≥ 4.",
            },
            "suggested_filename": {
                "type": "string",
                "description": "Evidence HTML filename. Required for score ≥ 4.",
            },
            "relations": {
                "type": "array",
                "description": "Relations to existing papers.",
                "items": RELATION_SCHEMA,
            },
            "chart_updates": {
                "type": "object",
                "description": "Optional chart bar additions/updates.",
            },
            "evidence": {
                "type": "array",
                "description": "suggested_js 的 n、regimen、endpoint、result、bottomLine 中每一個數字的出處。score < 4 時可為空陣列。",
                "items": EVIDENCE_SCHEMA,
            },
        },
        "required": ["relevance_score", "contextual_analysis", "evidence"],
    },
}

ALL_TOOLS = [*AGENT_TOOLS, SUBMIT_CLASSIFICATION_TOOL]

# Output schema for the last-resort call. Structured outputs require
# additionalProperties: false on every object, so the free-form suggested_js and
# chart_updates fields of submit_classification are left out; the reviewer writes
# those by hand for the rare paper classified this way.
_RESCUE_FIELDS = (
    "relevance_score",
    "contextual_analysis",
    "bottom_line",
    "suggested_filename",
    "relations",
    "evidence",
)
RESCUE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {k: SUBMIT_CLASSIFICATION_TOOL["input_schema"]["properties"][k] for k in _RESCUE_FIELDS},
    "required": list(_RESCUE_FIELDS),
    "additionalProperties": False,
}


def _system_blocks(system_prompt: str) -> list[dict]:
    """The topic's system prompt as one cached block.

    Tools render before system, so this breakpoint covers tools + system. Every paper
    of a topic after the first reads that prefix from the cache. Without it the only
    breakpoint is the automatic one after the paper itself, so each paper wrote an
    entry no other paper could read (first live run: 198K tokens written, 10K read).
    """
    return [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]


def _create_message(client: Anthropic, system_prompt: str, messages: list[dict], **overrides):
    """Send one agent turn. The tools array and system prompt stay identical on every
    call so that earlier thinking blocks remain valid; overrides only touch per-call fields."""
    params = {
        "model": CLASSIFY_MODEL,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": CLASSIFY_EFFORT},
        "system": _system_blocks(system_prompt),
        "tools": ALL_TOOLS,
        "messages": messages,
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
        # Automatic breakpoint at the end of the conversation: later turns of the same
        # paper's tool loop read everything sent so far.
        "cache_control": {"type": "ephemeral"},
    }
    params.update(overrides)
    response = client.beta.messages.create(**params)
    USAGE.record(response, CLASSIFY_MODEL)
    return response


def _refusal_note(response) -> str:
    category = getattr(response.stop_details, "category", None) if response.stop_details else None
    return f"(Model declined to classify this paper, refusal category: {category} — needs manual review)"


def _mark_for_review(paper: dict, note: str) -> dict:
    """Route a paper to the manual review queue instead of dropping it or scoring it 0."""
    paper["ai_score"] = None
    paper["ai_analysis"] = note
    paper["ai_bottom_line"] = ""
    paper["ai_suggested_js"] = None
    paper["ai_suggested_filename"] = ""
    paper["ai_relations"] = []
    paper["ai_chart_updates"] = None
    paper["ai_evidence"] = []
    paper["ai_parse_failed"] = True
    return paper


def _build_batch_context(paper: dict, all_candidates: list[dict]) -> str:
    """Build a summary of other papers in the same batch for cross-paper context."""
    same_topic = [
        c
        for c in all_candidates
        if c.get("topic") == paper.get("topic")
        and c.get("doi", "x") != paper.get("doi", "y")  # exclude self
        and c.get("pmid", "x") != paper.get("pmid", "y")
    ]
    other_topics = [
        c for c in all_candidates if c.get("topic") != paper.get("topic") and c.get("doi", "x") != paper.get("doi", "y")
    ]

    if not same_topic and not other_topics:
        return ""

    lines = ["\n\n---\n## 本批其他候選文獻（供相對判斷參考）\n"]

    if same_topic:
        lines.append(f"### 同主題（{paper.get('topic', '')}）")
        for c in same_topic[:5]:
            score_tag = f" [已評: {c['ai_score']}/5]" if c.get("ai_score") is not None else ""
            lines.append(f"- {c.get('title', '')[:100]}{score_tag}")
            if c.get("abstract"):
                lines.append(f"  _{c['abstract'][:150]}..._")

    if other_topics:
        lines.append("\n### 其他主題")
        for c in other_topics[:3]:
            lines.append(f"- [{c.get('topic', '')}] {c.get('title', '')[:100]}")

    lines.append(
        "\n注意：如果你發現本篇與同批其他候選有「supersedes」或「contradicts」的關係，請在 contextual_analysis 中說明。"
    )
    return "\n".join(lines)


def _extract_submission(response) -> dict | None:
    """Return the submit_classification input if present in the response."""
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_classification":
            return block.input
    return None


def _apply_submission(paper: dict, result: dict) -> dict:
    """Write a submit_classification result onto the paper dict."""
    paper["ai_score"] = result.get("relevance_score", 0)
    paper["ai_analysis"] = result.get("contextual_analysis", "")
    paper["ai_bottom_line"] = result.get("bottom_line", "")
    paper["ai_suggested_js"] = result.get("suggested_js")
    paper["ai_suggested_filename"] = result.get("suggested_filename", "")
    paper["ai_relations"] = result.get("relations", [])
    paper["ai_chart_updates"] = result.get("chart_updates")
    paper["ai_evidence"] = result.get("evidence", [])
    paper["ai_parse_failed"] = False
    return paper


def _append_user_text(messages: list[dict], text: str) -> None:
    """Append a user text message, merging if the last message is already a user turn."""
    if messages and messages[-1]["role"] == "user":
        content = messages[-1]["content"]
        if isinstance(content, str):
            messages[-1]["content"] = f"{content}\n\n{text}"
        else:
            messages[-1]["content"] = [*content, {"type": "text", "text": text}]
    else:
        messages.append({"role": "user", "content": text})


def classify_paper(client: Anthropic, paper: dict, all_candidates: list[dict] | None = None) -> dict:
    """Classify a single paper using its topic-specific agent with tool use.

    The agent MUST call submit_classification as its final action.
    Research tools (search_pubmed, etc.) are called in earlier turns.
    all_candidates: the full batch for cross-paper context.
    """
    topic = paper.get("topic", "")
    system_prompt = build_system_prompt(topic)
    user_prompt = build_paper_prompt(paper)

    # Inject batch context so agent can make relative judgments
    if all_candidates and len(all_candidates) > 1:
        user_prompt += _build_batch_context(paper, all_candidates)

    messages: list[dict] = [{"role": "user", "content": user_prompt}]

    for _turn in range(MAX_AGENT_TURNS):
        response = _create_message(client, system_prompt, messages)

        # Even the fallback model declined: retrying the same request won't help.
        if response.stop_reason == "refusal":
            print(f"    [WARN] {_refusal_note(response)}", file=sys.stderr)
            return _mark_for_review(paper, _refusal_note(response))

        # Log thinking blocks
        for block in response.content:
            if block.type == "thinking" and block.thinking.strip():
                thought = block.thinking.strip().replace("\n", " ")
                print(f"    [CoT] {thought[:300]}")

        # Check for submit_classification tool call — this is the final answer
        submission = _extract_submission(response)
        if submission is not None:
            return _apply_submission(paper, submission)

        # If agent wants to use research tools (not submit_classification)
        if response.stop_reason == "tool_use":
            # Log reasoning text before tool calls
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    print(f"    [Think] {block.text.strip()[:200]}")

            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use" and block.name != "submit_classification":
                    print(f"    [Tool] {block.name}({json.dumps(block.input, ensure_ascii=False)[:80]})")
                    result = execute_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            else:
                # Assistant turn had no executable tool calls — drop it to keep
                # the conversation valid (no dangling tool_use without result).
                messages.pop()
                _append_user_text(messages, FORCE_SUBMIT_PROMPT)
            continue

        # end_turn without submit_classification — agent forgot to call the tool.
        # Nudge it once more instead of giving up immediately.
        if response.stop_reason == "end_turn":
            print("    [WARN] Agent ended without calling submit_classification", file=sys.stderr)
            messages.append({"role": "assistant", "content": response.content})
            _append_user_text(messages, FORCE_SUBMIT_PROMPT)
            continue

        # max_tokens or another unexpected stop: resending the same turn would repeat it.
        print(f"    [WARN] Unexpected stop_reason={response.stop_reason}; going to rescue call", file=sys.stderr)
        break

    # Turn budget exhausted. The model no longer accepts a forced tool_choice, so the
    # last call disables tools and constrains the reply to the classification JSON
    # schema instead; a slow researcher still isn't reported as a parse failure.
    try:
        _append_user_text(messages, RESCUE_PROMPT)
        final_response = _create_message(
            client,
            system_prompt,
            messages,
            tool_choice={"type": "none"},
            output_config={
                "effort": CLASSIFY_EFFORT,
                "format": {"type": "json_schema", "schema": RESCUE_OUTPUT_SCHEMA},
            },
        )
        if final_response.stop_reason == "refusal":
            return _mark_for_review(paper, _refusal_note(final_response))
        text = next((b.text for b in final_response.content if b.type == "text"), "")
        submission = json.loads(text)
        print("    [INFO] Recovered classification via structured output")
        return _apply_submission(paper, submission)
    except Exception as exc:  # network/API/JSON errors must not crash the whole run
        print(f"    [WARN] Structured-output rescue failed: {exc}", file=sys.stderr)

    # If we get here, the agent never called submit_classification properly.
    # Mark as parse failure — NOT as score 0. This goes to a review queue.
    print("    [WARN] Classification parse failed — marking for manual review", file=sys.stderr)
    return _mark_for_review(paper, "(Agent did not produce structured classification — needs manual review)")


def classify_all(candidates: list[dict], dry_run: bool = False) -> list[dict]:
    """Classify a list of candidate papers using topic-specific agents.

    Returns papers that pass the relevance threshold OR had parse failures
    (parse failures go to review, not silently dropped).
    """
    if not candidates:
        print("[Classify] No candidates to classify.")
        return []

    if not ANTHROPIC_API_KEY:
        print("[Classify] No ANTHROPIC_API_KEY set. Skipping AI classification.", file=sys.stderr)
        for c in candidates:
            c["ai_score"] = None
            c["ai_analysis"] = "(AI classification skipped — no API key)"
            c["ai_parse_failed"] = False
        return candidates

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    classified = []

    # Sort by topic so same-topic papers are processed together.
    # Earlier papers' scores become visible to later papers in the batch context.
    candidates_sorted = sorted(candidates, key=lambda c: c.get("topic", ""))

    for i, paper in enumerate(candidates_sorted):
        title_short = paper.get("title", "")[:60]
        print(f"[Agent] ({i + 1}/{len(candidates_sorted)}) [{paper.get('topic', '')}] {title_short}...")

        if dry_run:
            paper["ai_score"] = None
            paper["ai_analysis"] = "(dry run)"
            paper["ai_parse_failed"] = False
            classified.append(paper)
            continue

        paper = classify_paper(client, paper, all_candidates=candidates_sorted)
        classified.append(paper)

        if paper.get("ai_parse_failed"):
            print("  ⚠ Parse failed — will create review issue")
        else:
            print(f"  Score: {paper['ai_score']}/5")

    # Keep papers that: pass threshold, OR had parse failures, OR had no API key
    high_relevance = []
    low_relevance = []
    parse_failures = []

    for c in classified:
        if c.get("ai_parse_failed"):
            parse_failures.append(c)
        elif c.get("ai_score") is None:
            high_relevance.append(c)  # No API key — pass through
        elif c["ai_score"] >= RELEVANCE_THRESHOLD:
            high_relevance.append(c)
        else:
            low_relevance.append(c)

    if low_relevance:
        print(f"[Classify] Filtered out {len(low_relevance)} low-relevance papers (score < {RELEVANCE_THRESHOLD})")
    if parse_failures:
        print(f"[Classify] {len(parse_failures)} papers had parse failures — sending to review")

    return high_relevance + parse_failures
