"""Search every source switched on for a subscriber, and merge what they find.

Each source is a module here with NAME and search(sub, query, since, limit) -> [paper dicts].
To add one: write the module and add it to SOURCES.

Check what each source returns for a subscriber (no ranking, no Kimi, no posting):
    python -m digest.sources wang_lab
"""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

from digest import paper
from digest.sources import arxiv, europepmc, openalex, pubmed, semantic_scholar

# Key under sources: in config -> module. Order = merge priority: when several sources have
# the same paper, details from the earlier one are kept (PubMed has the richest author data).
SOURCES = {
    "pubmed": pubmed,
    "europepmc": europepmc,
    "openalex": openalex,
    "semantic_scholar": semantic_scholar,
    "arxiv": arxiv,
}


def enabled(sub):
    """{source key: settings incl. query} for the sources switched on. PubMed falls back to the
    top-level query:. A subscriber without a sources: section searches PubMed only."""
    cfg = sub.get("sources") or {"pubmed": {"enabled": True}}
    out = {}
    for key, s in cfg.items():
        s = dict(s or {})
        if not s.get("enabled"):
            continue
        if key == "pubmed" and not s.get("query"):
            s["query"] = sub.get("query")
        out[key] = s
    return out


def check(sub):
    """Problems with the subscriber's sources: settings (empty list if fine)."""
    srcs = enabled(sub)
    if not srcs:
        return ["no source is switched on under sources:"]
    problems = [f"sources.{k} is not a known source (known: {', '.join(SOURCES)})"
                for k in srcs if k not in SOURCES]
    problems += [f"sources.{k} is on but has no query" for k, s in srcs.items()
                 if k in SOURCES and not s.get("query")]
    return problems


def _journal_ok(p, whitelist):
    """PubMed applies journals: in its own query; for other sources, match the journal name."""
    return "PubMed" in p["sources"] or paper.norm_title(p["journal"]) in whitelist


def search_all(sub):
    """Papers from every source switched on, duplicates merged, journals: whitelist applied.
    Returns (papers, report) where report is {source name: count or the exception it raised}."""
    srcs = enabled(sub)
    since = dt.date.today() - dt.timedelta(days=sub["days_back"])
    default_limit = sub.get("candidate_pool", 50)

    def run(key):
        s = srcs[key]
        return SOURCES[key].search(sub, s["query"], since, s.get("candidate_pool", default_limit))

    results, report = {}, {}
    with ThreadPoolExecutor(max_workers=len(srcs)) as pool:
        futures = {key: pool.submit(run, key) for key in srcs}
        for key, f in futures.items():
            try:
                results[key] = f.result()
                report[SOURCES[key].NAME] = len(results[key])
            except Exception as e:              # one source down shouldn't stop the others
                report[SOURCES[key].NAME] = e
    if not results:
        raise RuntimeError("every source failed: " + "; ".join(f"{n}: {e}" for n, e in report.items()))

    papers = paper.merge([p for key in SOURCES if key in results for p in results[key]])
    whitelist = {paper.norm_title(j) for j in sub.get("journals") or []}
    if whitelist:
        papers = [p for p in papers if _journal_ok(p, whitelist)]
    return papers, report


def describe(report):
    """'PubMed 42, arXiv 7, Semantic Scholar failed (429 ...)'"""
    return ", ".join(f"{n} {v}" if isinstance(v, int) else f"{n} failed ({v})" for n, v in report.items())

