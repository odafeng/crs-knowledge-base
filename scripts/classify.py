"""Layer 2: Topic-specific AI agents with tool use for paper classification.

Each agent runs in an agentic loop with research tools AND a mandatory
submit_classification tool that forces structured JSON output.
No more fragile regex-based JSON extraction from free-form text.
"""

import json
import sys

from anthropic import APIError, Anthropic

from agent_tools import AGENT_TOOLS, execute_tool
from config import ANTHROPIC_API_KEY, CLASSIFY_MODEL, RELEVANCE_THRESHOLD
from topic_agents import build_paper_prompt, build_system_prompt

MAX_AGENT_TURNS = 8  # Max tool-use rounds per paper
QUOTA_ERROR_KEYWORDS = ("usage limit", "rate limit", "quota")

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
                "items": {
                    "type": "object",
                    "properties": {
                        "targetId": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["builds_on", "supersedes", "subgroup_of", "same_regimen", "contradicts"],
                        },
                    },
                    "required": ["targetId", "type"],
                },
            },
            "chart_updates": {
                "type": "object",
                "description": "Optional chart bar additions/updates.",
            },
        },
        "required": ["relevance_score", "contextual_analysis"],
    },
}

ALL_TOOLS = [*AGENT_TOOLS, SUBMIT_CLASSIFICATION_TOOL]


def _mark_for_manual_review(paper: dict, reason: str) -> dict:
    """Mark a paper for manual review when AI classification is unavailable."""
    paper["ai_score"] = None
    paper["ai_analysis"] = f"(AI classification unavailable - {reason}; needs manual review)"
    paper["ai_bottom_line"] = ""
    paper["ai_suggested_js"] = None
    paper["ai_suggested_filename"] = ""
    paper["ai_relations"] = []
    paper["ai_chart_updates"] = None
    paper["ai_parse_failed"] = True
    return paper


def _summarize_api_error(exc: APIError) -> str:
    """Return a short, issue-friendly reason for an Anthropic API failure."""
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code == 429:
        return "Anthropic API quota or rate limit reached"

    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                message = message.lower()
                if any(keyword in message for keyword in QUOTA_ERROR_KEYWORDS):
                    return "Anthropic API quota or rate limit reached"

    if status_code is not None:
        return f"Anthropic API request failed (HTTP {status_code})"

    return "Anthropic API request failed"


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
        response = client.messages.create(
            model=CLASSIFY_MODEL,
            max_tokens=8000,
            thinking={"type": "enabled", "budget_tokens": 4000},
            system=system_prompt,
            tools=ALL_TOOLS,
            messages=messages,
        )

        # Log thinking blocks
        for block in response.content:
            if block.type == "thinking" and block.thinking.strip():
                thought = block.thinking.strip().replace("\n", " ")
                print(f"    [CoT] {thought[:300]}")

        # Check for submit_classification tool call — this is the final answer
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_classification":
                result = block.input  # Already structured JSON from tool schema
                paper["ai_score"] = result.get("relevance_score", 0)
                paper["ai_analysis"] = result.get("contextual_analysis", "")
                paper["ai_bottom_line"] = result.get("bottom_line", "")
                paper["ai_suggested_js"] = result.get("suggested_js")
                paper["ai_suggested_filename"] = result.get("suggested_filename", "")
                paper["ai_relations"] = result.get("relations", [])
                paper["ai_chart_updates"] = result.get("chart_updates")
                paper["ai_parse_failed"] = False
                return paper

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
            continue

        # end_turn without submit_classification — agent forgot to call the tool
        if response.stop_reason == "end_turn":
            print("    [WARN] Agent ended without calling submit_classification", file=sys.stderr)
            break

    # If we get here, the agent never called submit_classification properly.
    # Mark as parse failure — NOT as score 0. This goes to a review queue.
    print("    [WARN] Classification parse failed — marking for manual review", file=sys.stderr)
    return _mark_for_manual_review(paper, "Agent did not produce structured classification")


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

    api_failure_reason = None

    for i, paper in enumerate(candidates_sorted):
        title_short = paper.get("title", "")[:60]
        print(f"[Agent] ({i + 1}/{len(candidates_sorted)}) [{paper.get('topic', '')}] {title_short}...")

        if dry_run:
            paper["ai_score"] = None
            paper["ai_analysis"] = "(dry run)"
            paper["ai_parse_failed"] = False
            classified.append(paper)
            continue

        if api_failure_reason is not None:
            paper = _mark_for_manual_review(paper, api_failure_reason)
            print(f"  [WARN] {api_failure_reason} — sending to review")
            classified.append(paper)
            continue

        try:
            paper = classify_paper(client, paper, all_candidates=candidates_sorted)
        except APIError as exc:
            api_failure_reason = _summarize_api_error(exc)
            print(
                f"[Classify] {api_failure_reason}. Current and remaining papers will be sent to review.",
                file=sys.stderr,
            )
            paper = _mark_for_manual_review(paper, api_failure_reason)
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
