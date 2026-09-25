"""OpenAlex helpers: look up authors' h-index and journals' citation impact.

Also a tool to find an author's OpenAlex ID (names are ambiguous, IDs aren't):
    python -m digest.openalex "Meng Wang"
"""
import os
import re
import sys
import unicodedata

import requests

from digest import paper as _paper

BASE = "https://api.openalex.org"
KEY = os.getenv("OPENALEX_API_KEY")
WORK_FIELDS = "id,doi,type,authorships,primary_location,keywords"
session = requests.Session()
_author_cache, _source_cache = {}, {}


def _get(path, **params):
    if KEY:
        params["api_key"] = KEY
    r = session.get(f"{BASE}/{path}", params=params, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _short(url):
    """'https://openalex.org/A123' -> 'A123'"""
    return url.rsplit("/", 1)[-1] if url else None


def _clean_doi(doi):
    return doi.lower().replace("https://doi.org/", "") if doi else None


def _author_id(authorship):
    """OpenAlex author ID ('A123'), or None if OpenAlex couldn't identify the author."""
    return _short((authorship.get("author") or {}).get("id"))


def _name_tokens(name):
    """'Jürgen El-Sayed' -> {'jurgen', 'el', 'sayed'} (lowercase, accents stripped)"""
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return set(re.findall(r"[a-z]+", name.lower()))


def _find_authorship(auths, pos, last_name):
    """OpenAlex authorship of the PubMed author at position `pos`, checked by last name.
    Author order usually matches PubMed; if not, use the only author with that last name."""
    want = _name_tokens(last_name)

    def same(a):
        names = (_name_tokens(a.get("raw_author_name"))
                 | _name_tokens((a.get("author") or {}).get("display_name")))
        return bool(want) and want <= names

    if pos < len(auths) and same(auths[pos]):
        return auths[pos]
    hits = [a for a in auths if same(a)]
    return hits[0] if len(hits) == 1 else None


# ---------- Find each paper in OpenAlex ----------
def _lookup_works(papers):
    """Return {paper key: openalex_work}. Reuses works the OpenAlex search already returned,
    then bulk lookup by DOI, then single lookups by PMID or OpenAlex ID for the rest."""
    found = {_paper.key(p): p["oa_work"] for p in papers if p.get("oa_work")}
    todo = [p for p in papers if _paper.key(p) not in found]
    bulk = [p for p in todo if p["doi"] and not any(c in p["doi"] for c in ",|")]
    for i in range(0, len(bulk), 50):                 # max 50 DOIs per request
        chunk = bulk[i:i + 50]
        data = _get("works", filter="doi:" + "|".join(p["doi"] for p in chunk),
                    per_page=50, select=WORK_FIELDS)
        by_doi = {_clean_doi(w["doi"]): w for w in data["results"] if w.get("doi")}
        for p in chunk:
            if p["doi"] in by_doi:
                found[_paper.key(p)] = by_doi[p["doi"]]

    for p in todo:                                    # fallback: single lookups
        if _paper.key(p) in found:
            continue
        for path in ([f"works/pmid:{p['pmid']}"] if p.get("pmid") else []) + \
                    ([f"works/{p['openalex_id']}"] if p.get("openalex_id") else []):
            w = _get(path, select=WORK_FIELDS)
            if w:
                found[_paper.key(p)] = w
                break
    return found


# ---------- Author and journal metrics (cached within a run) ----------
def _author_dict(a, aid):
    return {
        "id": aid,
        "name": a.get("display_name", "?"),
        "h": (a.get("summary_stats") or {}).get("h_index") or 0,
    }


def prefetch_authors(aids):
    """Fill the author cache with up to 50 authors per request. If the batch request fails,
    author_info() still looks each one up on its own."""
    todo = [a for a in dict.fromkeys(aids) if a and a not in _author_cache]
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        try:
            data = _get("authors", filter="openalex:" + "|".join(chunk), per_page=50,
                        select="id,display_name,summary_stats")
        except requests.HTTPError:
            return
        for a in (data or {}).get("results", []):
            aid = _short(a.get("id"))
            _author_cache[aid] = _author_dict(a, aid)


def author_info(aid):
    if aid not in _author_cache:
        a = _get(f"authors/{aid}", select="id,display_name,summary_stats") or {}
        _author_cache[aid] = _author_dict(a, aid)
    return _author_cache[aid]


def source_info(sid):
    if sid not in _source_cache:
        s = _get(f"sources/{sid}", select="id,display_name,summary_stats") or {}
        _source_cache[sid] = {
            "id": sid,
            "name": s.get("display_name", "?"),
            # ~ impact factor: avg citations of the journal's papers from the past 2 years
            "citedness": round((s.get("summary_stats") or {}).get("2yr_mean_citedness") or 0, 2),
        }
    return _source_cache[sid]


def _key_author_roles(p, w):
    """{author ID: roles} for the key authors (the highest h-index among them counts):
         lead:           co-first authors flagged in PubMed, else the first author
         corresponding:  corresponding authors flagged in OpenAlex, else the last author (usually the PI)"""
    all_auths = w.get("authorships", [])           # unfiltered, so positions line up with PubMed
    auths = [a for a in all_auths if _author_id(a)]
    firsts = [a for a in (_find_authorship(all_auths, pos, last) for pos, last in p.get("co_first", []))
              if a and _author_id(a)]
    firsts = firsts or [a for a in auths if a.get("author_position") == "first"]
    corrs = ([a for a in auths if a.get("is_corresponding")]
             or [a for a in auths if a.get("author_position") == "last"])
    roles = {}                                     # author ID -> e.g. ["first", "corresponding"]
    for a in firsts:
        roles.setdefault(_author_id(a), []).append("co-first" if len(firsts) > 1 else "first")
    for a in corrs:
        roles.setdefault(_author_id(a), []).append("corresponding" if a.get("is_corresponding") else "last")
    return roles


def enrich(papers):
    """Add OpenAlex author/journal metrics to each paper dict (in place). Also marks preprints
    and fills in keywords for papers whose source had none (arXiv, Semantic Scholar)."""
    works = _lookup_works(papers)
    roles = {}
    for p in papers:
        w = works.get(_paper.key(p))
        p["oa_matched"] = w is not None
        if not w:
            continue
        auths = [a for a in w.get("authorships", []) if _author_id(a)]
        p["author_ids"] = [_author_id(a) for a in auths]
        p["author_names"] = [a["author"].get("display_name", "") for a in auths]
        if w.get("type") == "preprint":
            p["preprint"] = True
        if not p["keywords"]:
            p["keywords"] = [k.get("display_name") for k in w.get("keywords") or [] if k.get("display_name")]
        roles[_paper.key(p)] = _key_author_roles(p, w)

    prefetch_authors([aid for r in roles.values() for aid in r])
    for p in papers:
        w = works.get(_paper.key(p))
        if not w:
            continue
        # Copy the cached author dicts so the per-paper role isn't shared between papers
        p["key_authors"] = [{**author_info(aid), "role": "+".join(r)} for aid, r in roles[_paper.key(p)].items()]
        p["top_author"] = max(p["key_authors"], key=lambda x: x["h"], default=None)
        src = (w.get("primary_location") or {}).get("source") or {}
        p["source"] = source_info(_short(src["id"])) if src.get("id") else None


# ---------- CLI: find an author's ID ----------
if __name__ == "__main__":
    name = " ".join(sys.argv[1:])
    if not name:
        sys.exit('Usage: python -m digest.openalex "Author Name"')
    data = _get("authors", search=name, per_page=10,
                select="id,display_name,summary_stats,works_count,last_known_institutions")
    for a in data["results"]:
        inst = ", ".join(i["display_name"] for i in a.get("last_known_institutions") or [])
        h = (a.get("summary_stats") or {}).get("h_index", 0)
        print(f"{_short(a['id']):<13} h={h:<4} works={a['works_count']:<5} "
              f"{a['display_name']}  |  {inst}")