"""Every internal href and src in the built site must point at a file that exists.

python tools/check_links.py site
"""

import re
import sys
from pathlib import Path

site = Path(sys.argv[1])
LINK = re.compile(r'(?:href|src)="([^"#]+)(?:#[^"]*)?"')
broken, checked = [], 0
for page in sorted(site.rglob("*.html")):
    for target in LINK.findall(page.read_text(encoding="utf-8")):
        if target.startswith(("http:", "https:", "mailto:", "data:")):
            continue
        checked += 1
        resolved = (page.parent / target).resolve()
        if resolved.is_dir():
            resolved = resolved / "index.html"
        if not resolved.is_file():
            broken.append(f"{page.relative_to(site)} -> {target}")
print(f"internal links checked: {checked} | broken: {len(broken)}")
for line in broken[:20]:
    print("  -", line)
sys.exit(1 if broken else 0)
