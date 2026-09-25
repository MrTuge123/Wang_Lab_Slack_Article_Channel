"""Check what each source returns for a subscriber (no ranking, no Kimi, no posting):
    python -m digest.sources wang_lab
"""
import sys

from digest import paper
from digest.config import load_subscribers
from digest.sources import SOURCES, describe, enabled, search_all

if len(sys.argv) != 2:
    sys.exit("Usage: python -m digest.sources <subscriber>")
sub = load_subscribers(sys.argv[1])[0]
for key, s in enabled(sub).items():
    print(f"{SOURCES[key].NAME:<17} query: {s['query']}")
papers, report = search_all(sub)
print("\nFound:", describe(report))
total = sum(v for v in report.values() if isinstance(v, int))
print(f"{len(papers)} distinct papers after merging duplicates (from {total} records)\n")
for p in papers:
    tag = " [preprint]" if p["preprint"] else ""
    print(f"- {p['title'][:90]}{tag}\n    {', '.join(p['sources'])} · {p['journal'][:50]} · {paper.url(p)}")
