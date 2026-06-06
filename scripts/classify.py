"""Layer 2: Use topic-specific Claude sub-agents to classify and contextualize papers."""

import argparse
import json
import sys

from anthropic import Anthropic

from config import ANTHROPIC_API_KEY, CLASSIFY_MODEL, RELEVANCE_THRESHOLD
from topic_agents import build_paper_prompt, build_system_prompt


def classify_paper(client, paper):
    """Classify a single paper using its topic-specific sub-agent.

    Returns the paper dict augmented with classification results.
    """
    topic = paper.get("topic", "")
    system_prompt = build_system_prompt(topic)
    user_prompt = build_paper_prompt(paper)

    response = client.messages.create(
        model=CLASSIFY_MODEL,
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = response.content[0].text

    # Parse JSON from response (handle markdown code blocks)
    json_str = raw
    if "```json" in raw:
        json_str = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        json_str = raw.split("```")[1].split("```")[0]

    try:
        result = json.loads(json_str.strip())
    except json.JSONDecodeError:
        print(f"  [WARN] Failed to parse AI response for: {paper.get('title', '')[:60]}", file=sys.stderr)
        result = {"relevance_score": 0, "contextual_analysis": raw[:500]}

    paper["ai_score"] = result.get("relevance_score", 0)
    paper["ai_analysis"] = result.get("contextual_analysis", "")
    paper["ai_bottom_line"] = result.get("bottom_line", "")
    paper["ai_suggested_js"] = result.get("suggested_js")
    paper["ai_suggested_filename"] = result.get("suggested_filename", "")
    paper["ai_relations"] = result.get("relations", [])

    return paper


def classify_all(candidates, dry_run=False):
    """Classify a list of candidate papers. Returns filtered list (score >= threshold)."""
    if not candidates:
        print("[Classify] No candidates to classify.")
        return []

    if not ANTHROPIC_API_KEY:
        print("[Classify] No ANTHROPIC_API_KEY set. Skipping AI classification.", file=sys.stderr)
        # Pass through all candidates without scoring
        for c in candidates:
            c["ai_score"] = None
            c["ai_analysis"] = "(AI classification skipped — no API key)"
        return candidates

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    classified = []

    for i, paper in enumerate(candidates):
        title_short = paper.get("title", "")[:60]
        print(f"[Classify] ({i+1}/{len(candidates)}) [{paper.get('topic','')}] {title_short}...")

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
