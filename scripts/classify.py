"""Layer 2: Topic-specific AI agents with tool use for paper classification.

Each agent runs in an agentic loop — it can autonomously search PubMed,
fetch paper details, check existing KB papers, and browse web pages
before making its final classification decision.
"""

import argparse
import json
import sys

from anthropic import Anthropic

from agent_tools import AGENT_TOOLS, execute_tool
from config import ANTHROPIC_API_KEY, CLASSIFY_MODEL, RELEVANCE_THRESHOLD
from topic_agents import build_paper_prompt, build_system_prompt

MAX_AGENT_TURNS = 6  # Max tool-use rounds per paper


def classify_paper(client, paper):
    """Classify a single paper using its topic-specific agent with tool use.

    The agent runs in an agentic loop:
    1. Receives the candidate paper
    2. Can call tools (search_pubmed, fetch_paper_details, etc.)
    3. Continues until it produces a final JSON classification
    """
    topic = paper.get("topic", "")
    system_prompt = build_system_prompt(topic)
    user_prompt = build_paper_prompt(paper)

    messages = [{"role": "user", "content": user_prompt}]

    # Agentic loop
    for turn in range(MAX_AGENT_TURNS):
        response = client.messages.create(
            model=CLASSIFY_MODEL,
            max_tokens=8000,
            thinking={"type": "enabled", "budget_tokens": 4000},
            system=system_prompt,
            tools=AGENT_TOOLS,
            messages=messages,
        )

        # Log thinking blocks (chain of thought)
        for block in response.content:
            if block.type == "thinking" and block.thinking.strip():
                # Truncate for logs but show enough to understand reasoning
                thought = block.thinking.strip().replace("\n", " ")
                print(f"    [CoT] {thought[:300]}")

        # If agent is done (no more tool calls), extract final answer
        if response.stop_reason == "end_turn":
            return _extract_classification(paper, response)

        # If agent wants to use tools
        if response.stop_reason == "tool_use":
            # Log agent's reasoning before tool calls
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    print(f"    [Think] {block.text.strip()[:200]}")

            # Append assistant response (with tool_use blocks)
            messages.append({"role": "assistant", "content": response.content})

            # Execute each tool call
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    print(f"    [Tool] {tool_name}({json.dumps(tool_input, ensure_ascii=False)[:80]})")

                    result = execute_tool(tool_name, tool_input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            # Append tool results
            messages.append({"role": "user", "content": tool_results})
            continue

        # Any other stop reason — extract what we have
        return _extract_classification(paper, response)

    # If we hit max turns, extract from last response
    print(f"    [WARN] Agent hit max turns ({MAX_AGENT_TURNS})", file=sys.stderr)
    return _extract_classification(paper, response)


def _extract_classification(paper, response):
    """Extract structured classification from the agent's final response."""
    raw = ""
    for block in response.content:
        if block.type == "text":
            raw += block.text

    # Parse JSON from response
    json_str = raw
    if "```json" in raw:
        json_str = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        parts = raw.split("```")
        if len(parts) >= 2:
            json_str = parts[1]

    try:
        result = json.loads(json_str.strip())
    except json.JSONDecodeError:
        print(f"    [WARN] Failed to parse agent response as JSON", file=sys.stderr)
        result = {"relevance_score": 0, "contextual_analysis": raw[:500]}

    paper["ai_score"] = result.get("relevance_score", 0)
    paper["ai_analysis"] = result.get("contextual_analysis", "")
    paper["ai_bottom_line"] = result.get("bottom_line", "")
    paper["ai_suggested_js"] = result.get("suggested_js")
    paper["ai_suggested_filename"] = result.get("suggested_filename", "")
    paper["ai_relations"] = result.get("relations", [])
    paper["ai_chart_updates"] = result.get("chart_updates")

    return paper


def classify_all(candidates, dry_run=False):
    """Classify a list of candidate papers using topic-specific agents."""
    if not candidates:
        print("[Classify] No candidates to classify.")
        return []

    if not ANTHROPIC_API_KEY:
        print("[Classify] No ANTHROPIC_API_KEY set. Skipping AI classification.", file=sys.stderr)
        for c in candidates:
            c["ai_score"] = None
            c["ai_analysis"] = "(AI classification skipped — no API key)"
        return candidates

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    classified = []

    for i, paper in enumerate(candidates):
        title_short = paper.get("title", "")[:60]
        print(f"[Agent] ({i+1}/{len(candidates)}) [{paper.get('topic','')}] {title_short}...")

        if dry_run:
            paper["ai_score"] = None
            paper["ai_analysis"] = "(dry run)"
            classified.append(paper)
            continue

        paper = classify_paper(client, paper)
        classified.append(paper)
        print(f"  Score: {paper['ai_score']}/5")

    # Filter by threshold
    high_relevance = [c for c in classified if c.get("ai_score") is None or (c["ai_score"] and c["ai_score"] >= RELEVANCE_THRESHOLD)]
    low_relevance = [c for c in classified if c.get("ai_score") is not None and c["ai_score"] and c["ai_score"] < RELEVANCE_THRESHOLD]

    if low_relevance:
        print(f"[Classify] Filtered out {len(low_relevance)} low-relevance papers (score < {RELEVANCE_THRESHOLD})")

    return high_relevance


def main():
    parser = argparse.ArgumentParser(description="Classify papers with topic-specific AI agents")
    parser.add_argument("--input", help="JSON file with candidates (default: stdin)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.input:
        with open(args.input) as f:
            candidates = json.load(f)
    else:
        candidates = json.load(sys.stdin)

    results = classify_all(candidates, dry_run=args.dry_run)

    json.dump(results, sys.stdout, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
