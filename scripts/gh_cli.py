"""Thin wrapper around the gh CLI for issue and label operations."""

import subprocess
import sys

from config import GITHUB_TOKEN
from topics import LABEL_COLORS


def run_gh(args, input_text=None):
    """Run a gh CLI command. Returns (success, stdout)."""
    cmd = ["gh", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            input=input_text,
            env={"GH_TOKEN": GITHUB_TOKEN, "PATH": "/usr/bin:/usr/local/bin:/opt/homebrew/bin"}
            if GITHUB_TOKEN
            else None,
        )
        if result.returncode != 0:
            print(f"  [WARN] gh command failed: {result.stderr.strip()}", file=sys.stderr)
            return False, result.stderr
        return True, result.stdout.strip()
    except FileNotFoundError:
        print("  [ERROR] gh CLI not found. Install: https://cli.github.com", file=sys.stderr)
        return False, ""
    except subprocess.TimeoutExpired:
        print("  [WARN] gh command timed out", file=sys.stderr)
        return False, ""


def ensure_labels(labels: set[str]) -> None:
    """Create labels if they don't exist (idempotent)."""
    for label in labels:
        color = LABEL_COLORS.get(label)
        if color:
            run_gh(["label", "create", label, "--color", color, "--force"])
