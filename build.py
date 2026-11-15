"""Build the static site.

python build.py
"""

import argparse
from pathlib import Path

from sitegen.load import load_kb
from sitegen.render import build_site

parser = argparse.ArgumentParser()
parser.add_argument("--kb", type=Path, default=Path("data/papers.json"))
parser.add_argument("--news", type=Path, default=Path("data/news.json"), help="news stories")
parser.add_argument("--out", type=Path, default=Path("site"))
parser.add_argument(
    "--explicit-index", action="store_true", help="link to index.html by name, for hosts without directory indexes"
)
args = parser.parse_args()
print(build_site(load_kb(args.kb, args.news), args.out, args.explicit_index))
