"""Every candidate paper a subscriber's runs have ranked, kept for trend summaries:
history/<subscriber>.jsonl, one paper per line (JSON Lines).

- save_history(sid, ranked, posted):  add this run's ranked candidates. A paper that is already
      in the file (any shared PMID, DOI, arXiv ID or title, the same rule as seen/) updates its
      line instead of adding another: the newest run's score, rank and details win, first_seen and
      posted_at keep the earliest date, and an empty value never replaces a filled one.
- load_history(sid):  the records, one per paper, in the order they were first seen.

Also merges one history file into another (the GitHub workflow uses this):
    python -m digest.history merge FROM.jsonl INTO.jsonl
"""
import json
import os
import sys
from datetime import datetime, timezone

from digest import paper
from digest.store import atomic_write

HISTORY_DIR = "history"


def history_path(sid):
    return os.path.join(HISTORY_DIR, f"{sid}.jsonl")


def record(p, rank, today, posted):
    """What to keep of one ranked paper: a snapshot from this run."""
    return {
        "title": p["title"],
        "score": p["score"],
        "rank": rank,                                   # 1 = best candidate of that run
        "posted_at": today if posted else None,         # None = never posted
        "first_seen": today,
        "last_seen": today,
        "journal": p["journal"],
        "journal_citedness": (p.get("source") or {}).get("citedness"),   # ~ impact factor; None = unknown
        "preprint": p["preprint"],
        "top_author": p.get("top_author"),              # {id, name, h, role}
        "key_authors": p.get("key_authors", []),        # co-first + corresponding authors, with h-index
        "keyword_hits": p.get("keyword_hits", []),
        "keywords": p["keywords"],
        "summary": p.get("summary"),                    # Kimi's summary (posted papers only)
        "abstract": p["abstract"],
        "link": paper.url(p),
        "pmid": p["pmid"],
        "doi": p["doi"],
        "arxiv_id": p["arxiv_id"],
        "sources": p["sources"],
        "ids": sorted(paper.ids(p)),                    # what duplicates are matched on
    }


def _merge(a, b):
    """One record from two records of the same paper."""
    old, new = (b, a) if b["last_seen"] < a["last_seen"] else (a, b)
    out = {**old, **{k: v for k, v in new.items() if v not in (None, "", [])}}
    out["ids"] = sorted(set(a["ids"]) | set(b["ids"]))
    out["first_seen"] = min(a["first_seen"], b["first_seen"])
    posted = [d for d in (a["posted_at"], b["posted_at"]) if d]
    out["posted_at"] = min(posted) if posted else None
    return out


def _combine(records):
    """Merge records that share any ID into one, keeping the order papers were first added."""
    out, index = [], {}                                 # index: ID -> position in out
    for r in records:
        hits = sorted({index[i] for i in r["ids"] if i in index})
        if not hits:
            index.update({i: len(out) for i in r["ids"]})
            out.append(r)
            continue
        keep = hits[0]
        for h in hits[1:]:                              # r links papers that were separate until now
            out[keep], out[h] = _merge(out[keep], out[h]), None
        out[keep] = _merge(out[keep], r)
        index.update({i: keep for i in out[keep]["ids"]})
    return [r for r in out if r is not None]


def read_history(path):
    """The records in a history file, one per paper (lines of the same paper, e.g. after a
    git merge kept both versions, are combined)."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return _combine(json.loads(line) for line in f if line.strip())


def _write(path, records):
    lines = (json.dumps(r, ensure_ascii=False) + "\n" for r in _combine(records))
    atomic_write(path, "".join(lines), prefix=".history-")


def load_history(sid):
    return read_history(history_path(sid))


def save_history(sid, ranked, posted):
    """Add this run's candidates (best first, as ranked) to the subscriber's history.
    `posted` are the ones at least one chat received."""
    today = datetime.now(timezone.utc).date().isoformat()
    new = [record(p, rank, today, p in posted) for rank, p in enumerate(ranked, 1)]
    path = history_path(sid)
    _write(path, read_history(path) + new)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "merge":
        sys.exit("Usage: python -m digest.history merge FROM.jsonl INTO.jsonl")
    _write(sys.argv[3], read_history(sys.argv[3]) + read_history(sys.argv[2]))
