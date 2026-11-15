"""Token usage and estimated cost per pipeline run.

Printed at the end of each run and, on GitHub Actions, written to the job
summary, so the model choice can be judged on real numbers.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

# USD per million tokens: input, output, 5-minute cache write, cache read.
# Anthropic list prices as of 2026-11; check the pricing page before relying on them.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-2": (8.0, 40.0, 10.0, 0.20),
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.10),
    "claude-opus-4-8": (5.0, 25.0, 6.25, 0.50),
    "claude-opus-5": (5.0, 25.0, 6.25, 0.50),
}


def _tokens(usage, name: str) -> int:
    value = getattr(usage, name, 0)
    return value if isinstance(value, int) else 0


@dataclass
class ModelUsage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    def cost(self, model: str) -> float | None:
        if model not in PRICES:
            return None
        p_in, p_out, p_write, p_read = PRICES[model]
        return (
            self.input_tokens * p_in
            + self.output_tokens * p_out
            + self.cache_write_tokens * p_write
            + self.cache_read_tokens * p_read
        ) / 1_000_000


@dataclass
class UsageLog:
    by_model: dict[str, ModelUsage] = field(default_factory=dict)

    def record(self, response, requested_model: str) -> None:
        """Add one response's usage, priced by the model that actually served it."""
        model = response.model if isinstance(getattr(response, "model", None), str) else requested_model
        u = self.by_model.setdefault(model, ModelUsage())
        usage = getattr(response, "usage", None)
        u.requests += 1
        u.input_tokens += _tokens(usage, "input_tokens")
        u.output_tokens += _tokens(usage, "output_tokens")
        u.cache_write_tokens += _tokens(usage, "cache_creation_input_tokens")
        u.cache_read_tokens += _tokens(usage, "cache_read_input_tokens")

    def total_cost(self) -> float | None:
        costs = [u.cost(m) for m, u in self.by_model.items()]
        return None if any(c is None for c in costs) else sum(c for c in costs if c is not None)

    def summary_lines(self) -> list[str]:
        if not self.by_model:
            return ["[Usage] No API calls."]
        lines = []
        for model, u in self.by_model.items():
            cost = u.cost(model)
            lines.append(
                f"[Usage] {model}: {u.requests} requests, input {u.input_tokens:,} "
                f"(cache write {u.cache_write_tokens:,}, cache read {u.cache_read_tokens:,}), "
                f"output {u.output_tokens:,}, est. ${cost:.2f}"
                if cost is not None
                else f"[Usage] {model}: {u.requests} requests (no price on file)"
            )
        total = self.total_cost()
        if total is not None:
            lines.append(f"[Usage] Estimated total: ${total:.2f}")
        return lines

    def report(self) -> None:
        lines = self.summary_lines()
        print("\n" + "\n".join(lines))
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a") as f:
                f.write(
                    "### Paper Watch API usage\n\n"
                    + "\n".join(f"- {line.removeprefix('[Usage] ')}" for line in lines)
                    + "\n"
                )


# One log per process: the pipeline is a single run.
USAGE = UsageLog()
