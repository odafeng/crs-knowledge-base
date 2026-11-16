"""Take a bot-published paper (by id) or commentary (by DOI / PMID) off the site (ADR-0013)."""

import argparse
import sys

from content_store import content_session
from publish import PublishError, unpublish


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove an auto-published or accepted KB entry")
    parser.add_argument("--target", required=True, help="paper id, or commentary DOI / PMID")
    args = parser.parse_args()
    target = args.target.strip()
    try:
        with content_session("unpublish", target) as session:
            print(f"removed {session.done or session.record(unpublish(target, session.kb))}")
    except PublishError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
