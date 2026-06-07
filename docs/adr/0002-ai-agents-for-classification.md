# 0002. Topic-Specific AI Agents with Tool Use for Paper Classification

**Status**: Accepted

## Context

The pipeline needs to evaluate whether a new paper is clinically important. A single-shot LLM call ("read this abstract, give a score") worked initially but had two problems:

1. The model couldn't verify its own assumptions (e.g., "is this trial's predecessor already in our KB?")
2. Classification quality depended entirely on the abstract quality — if the abstract was sparse, the model guessed

We needed the model to be able to *research* before judging.

## Decision

Each of the 8 topics has a dedicated AI agent running in an agentic loop (max 8 turns). Each agent has:

- A topic-specific system prompt with full treatment evolution context
- 5 research tools: `search_pubmed`, `fetch_paper_details`, `lookup_existing_papers`, `web_fetch`, `query_guidelines`
- 1 output tool: `submit_classification` (forces structured JSON — no regex extraction)

The agent decides autonomously when to use tools and when to submit its answer.

## Consequences

- **Positive**: Agents can self-verify ("let me check if BREAKWATER Cohort 2 is already tracked")
- **Positive**: Multi-step reasoning logged via `[CoT]` blocks — fully auditable
- **Positive**: `submit_classification` tool eliminates JSON parsing failures
- **Negative**: Cost is ~4-8x a single API call per paper (multiple turns + thinking tokens)
- **Negative**: Latency: 50 papers × 8 turns = minutes, not seconds
- **Negative**: Agent behavior is non-deterministic — same paper may get different scores on different days
- **Negative**: If Anthropic API changes tool_use behavior, the loop could break silently
