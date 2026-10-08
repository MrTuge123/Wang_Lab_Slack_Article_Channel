"""How a digest's papers connect to the subscriber's earlier papers (history/), through their
reference lists from OpenAlex. No Kimi calls; about one OpenAlex request per digest.

- direct: a paper in this digest cites one in history (sent to the subscriber, or a candidate).
- shared: older works cited both by this digest's papers and by earlier ones. Works that most of
  history cites (GSEA, TCGA, field surveys) say little about how papers relate, so ones cited by
  more than connections.max_share of history are left out.

Earlier candidates count if they were posted or Kimi scored their relevance at least
connections.min_relevance. OpenAlex often gets a new paper's references weeks after it appears,
so earlier papers still missing them are looked up again (refresh_days) and saved to history/.
"""
import datetime as dt
from collections import Counter

from digest import openalex
from digest import paper as _paper
from digest.history import load_history

DEFAULTS = {"enabled": True, "min_relevance": 5, "max_share": 0.3, "max_items": 3, "refresh_days": 90}
MIN_FOR_GENERIC = 20            # only call a reference generic once this many earlier papers have references
MAX_REFRESH = 200               # earlier papers looked up again per run (4 OpenAlex requests at most)


def _surname(name):
    """'Xiaohong Wang' -> 'Wang'; 'Wang X' or 'Smith JA' (Europe PMC: initials last) -> 'Wang', 'Smith';
    'Wang, Xiaohong' -> 'Wang'."""
    name = name.strip()
    if "," in name:
        return name.split(",")[0].strip()
    parts = name.split()
    if len(parts) > 1 and parts[-1].isupper() and len(parts[-1].replace(".", "")) <= 3:
        return " ".join(parts[:-1])
    return parts[-1] if parts else ""


def cite_label(p):
    """Short citation for a paper: 'Wang et al. 2026', 'Wang and Li 2026', 'Wang 2026' (no year if unknown)."""
    names = [s.title() if s.isupper() and len(s) > 3 else s
             for s in (_surname(a) for a in p.get("authors") or []) if s]
    if not names:
        who = p["title"][:40].rstrip() + ("…" if len(p["title"]) > 40 else "")
    elif len(names) == 1:
        who = names[0]
    elif len(names) == 2:
        who = f"{names[0]} and {names[1]}"
    else:
        who = f"{names[0]} et al."
    return f"{who} {p['year']}" if p.get("year") else who


def settings(sub):
    return {**DEFAULTS, **(sub.get("connections") or {})}


def _counts(r, cfg):
    """True if an earlier candidate is worth comparing with (posted, or relevant enough, or not scored)."""
    rel = r.get("relevance")
    return bool(r.get("posted_at")) or rel is None or rel >= cfg["min_relevance"]


def _refresh(hist, cfg):
    """Look up references again for recent earlier papers that have none: by OpenAlex ID, or by DOI
    for papers saved before IDs were kept. Updates hist in place and returns what to save,
    {OpenAlex ID or DOI: {"openalex_id", "references"}} (see history.set_references)."""
    since = (dt.date.today() - dt.timedelta(days=cfg["refresh_days"])).isoformat()
    todo = [r for r in hist if not r.get("references") and r["first_seen"] >= since
            and (r.get("openalex_id") or r.get("doi"))][:MAX_REFRESH]
    if not todo:
        return {}
    by_id = openalex.works_by_id([r["openalex_id"] for r in todo if r.get("openalex_id")],
                                 select="id,referenced_works")
    by_doi = openalex.works_by_doi([r["doi"] for r in todo if not r.get("openalex_id")])
    updates = {}
    for r in todo:
        key = r.get("openalex_id") or r["doi"]
        w = by_id.get(key) if r.get("openalex_id") else by_doi.get(key)
        if not w:
            continue
        refs = [openalex._short(x) for x in w.get("referenced_works") or []]
        found_id = not r.get("openalex_id")
        r["openalex_id"] = r.get("openalex_id") or openalex._short(w.get("id"))
        if refs:
            r["references"] = refs
        if refs or found_id:
            updates[key] = {"openalex_id": r["openalex_id"], "references": refs}
    return updates


def find(top, sub):
    """(connections, refreshed). connections is None when there's nothing to show, else
    {"papers": n, "with_refs": k, "linked": earlier papers sharing references, "n_shared": shared works,
     "shared": [{"title", "year", "now", "earlier", "by": ['Wang et al. 2026', ...]}],
     "direct": [{"citing": 'Wang et al. 2026', "title", "date", "sent"}]}.
    refreshed is what to save to history/ (see history.set_references)."""
    cfg = settings(sub)
    if not cfg["enabled"] or not top:
        return None, {}
    current = set().union(*(_paper.ids(p) for p in top))
    hist = [r for r in load_history(sub["id"]) if not set(r["ids"]) & current and _counts(r, cfg)]
    if not hist:
        return None, {}
    refreshed = _refresh(hist, cfg)

    # Direct: a paper here cites an earlier one
    earlier = {r["openalex_id"]: r for r in hist if r.get("openalex_id")}
    direct = [{"citing": cite_label(p), "title": earlier[w]["title"], "sent": bool(earlier[w].get("posted_at")),
               "date": earlier[w].get("posted_at") or earlier[w]["first_seen"]}
              for p in top for w in dict.fromkeys(p.get("references") or []) if w in earlier]
    direct.sort(key=lambda d: (not d["sent"], d["date"]))

    # Shared: older works cited both here and earlier (minus the ones nearly everyone cites)
    with_refs = [r for r in hist if r.get("references")]
    before = Counter(w for r in with_refs for w in set(r["references"]))
    generic = ({w for w, n in before.items() if n > cfg["max_share"] * len(with_refs)}
               if len(with_refs) >= MIN_FOR_GENERIC else set())
    now = Counter(w for p in top for w in set(p.get("references") or []))
    shared = sorted((w for w in now if before.get(w) and w not in generic),
                    key=lambda w: (-now[w], -before[w]))
    linked = sum(bool(set(r["references"]) & set(shared)) for r in with_refs)
    if not shared and not direct:
        return None, refreshed

    names = openalex.works_by_id(shared[:cfg["max_items"]])
    return {
        "papers": len(top),
        "with_refs": sum(bool(p.get("references")) for p in top),
        "linked": linked,
        "n_shared": len(shared),
        "shared": [{"title": (names.get(w) or {}).get("display_name") or w,
                    "year": (names.get(w) or {}).get("publication_year"), "now": now[w], "earlier": before[w],
                    "by": [cite_label(p) for p in top if w in set(p.get("references") or [])]}
                   for w in shared[:cfg["max_items"]]],
        "direct": direct[:cfg["max_items"]],
        "n_direct": len(direct),
    }, refreshed
