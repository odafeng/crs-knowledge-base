# 0007. Force Structured Output via submit_classification Tool

**Status**: Accepted

## Context

The original classify.py parsed the agent's final text response as JSON using regex (````json ... ```` fence detection). This was fragile because:

1. Extended thinking + tool use responses contain mixed content blocks
2. The model sometimes wraps JSON in prose ("Here's my assessment: ...")
3. `json.loads` failure was silently mapped to `relevance_score: 0` — meaning any parse error made the paper disappear from the pipeline without trace

This is a **silent data loss** bug in a literature monitoring system.

## Decision

Add a `submit_classification` tool to the agent's tool list. The agent MUST call this tool as its final action. The tool's `input_schema` enforces the exact JSON shape we need. Claude's tool_use mechanism guarantees schema compliance.

Parse failures (agent ends without calling submit_classification) are now flagged as `ai_parse_failed: True` and routed to a review queue (GitHub Issue with `parse-failed` label), not silently dropped.

## Consequences

- **Positive**: Zero regex parsing of LLM output — the SDK handles JSON serialization
- **Positive**: Parse failures are visible, not silent
- **Positive**: Schema is enforced at the API level (tool input_schema validation)
- **Positive**: Agent can still do multi-step reasoning before submitting — the tool is just the "final commit"
- **Negative**: Adds one more tool to the context window (~200 tokens)
- **Negative**: If the model ignores instructions and never calls the tool, we get a parse failure (which is correctly handled, but wastes the API cost of that run)
- **Negative**: Cannot use `tool_choice: {type: "tool", name: "submit_classification"}` because that would prevent the agent from using research tools first
