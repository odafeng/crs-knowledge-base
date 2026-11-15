"""Take a bot-published paper (by id) or commentary (by DOI / PMID) off the site (ADR-0013)."""

import argparse
import sys

from publish import PublishError, unpublish


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove an auto-published or accepted KB entry")
    parser.add_argument("--target", required=True, help="paper id, or commentary DOI / PMID")
    args = parser.parse_args()
    try:
        print(f"removed {unpublish(args.target.strip())}")
    except PublishError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
