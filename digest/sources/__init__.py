"""Search every source switched on for a subscriber, and merge what they find.

Each source is a module here with NAME and search(sub, query, since, limit) -> [paper dicts].
To add one: write the module and add it to SOURCES.

Check what each source returns for a subscriber (no ranking, no Kimi, no posting):
    python -m digest.sources wang_lab
"""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

from digest import paper, query
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
    """{source key: its settings} for the sources switched on.
    A subscriber without a sources: section searches PubMed only."""
    cfg = sub.get("sources") or {"pubmed": {"enabled": True}}
    return {k: dict(v or {}) for k, v in cfg.items() if (v or {}).get("enabled")}


def check(sub):
    """Problems with the subscriber's query/topic and sources: settings (empty list if fine)."""
    srcs = enabled(sub)
    if not srcs:
        return ["no source is switched on under sources:"]
    problems = [f"sources.{k} is not a known source (known: {', '.join(SOURCES)})"
                for k in srcs if k not in SOURCES]
    if sub.get("query") and sub.get("topic"):
        problems.append("set either query: (boolean) or topic: (plain English), not both")
    elif sub.get("query"):
        try:
            query.parse(sub["query"])
        except query.QueryError as e:
            problems.append(f"query: {e}")
    need = [k for k, v in srcs.items() if k in SOURCES and not v.get("query")]
    if need and not (sub.get("query") or sub.get("topic")):
        problems.append("add query: or topic: (needed by " + ", ".join(f"sources.{k}" for k in need) + ")")
    return problems


def queries(sub):
    """({source key: query in that source's syntax}, the boolean query Kimi wrote or None).
    A source's own query: wins. Otherwise it's translated from the subscriber's query:
    (PubMed gets that text as is), or from topic: via a boolean query Kimi writes."""
    srcs = enabled(sub)
    raw, tree, written = sub.get("query"), None, None
    if any(not v.get("query") for v in srcs.values()):
        if sub.get("topic"):
            written, tree = query.from_topic(sub["topic"], sub["model"])
            raw = None
        else:
            tree = query.parse(raw)
    out = {}
    for k, v in srcs.items():
        if v.get("query"):
            out[k] = v["query"]
        elif k == "pubmed" and raw:
            out[k] = raw
        else:
            out[k] = query.render(tree, k)
    return out, written


def _journal_ok(p, whitelist):
    """PubMed applies journals: in its own query; for other sources, match the journal name."""
    return "PubMed" in p["sources"] or paper.norm_title(p["journal"]) in whitelist


def search_all(sub):
    """Papers from every source switched on, duplicates merged, journals: whitelist applied.
    Returns (papers, report) where report is {source name: count or the exception it raised}."""
    srcs = enabled(sub)
    qs, written = queries(sub)
    if written:
        print(f"Query Kimi wrote from the topic: {written}")
    since = dt.date.today() - dt.timedelta(days=sub["days_back"])
    default_limit = sub.get("candidate_pool", 50)

    def run(key):
        return SOURCES[key].search(sub, qs[key], since, srcs[key].get("candidate_pool", default_limit))

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

