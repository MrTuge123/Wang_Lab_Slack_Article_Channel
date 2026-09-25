"""OpenAlex helpers: look up authors' h-index and journals' citation impact.

Also a tool to find an author's OpenAlex ID (names are ambiguous, IDs aren't):
    python -m digest.openalex "Meng Wang"
"""
import os
import re
import sys
import unicodedata

import requests

BASE = "https://api.openalex.org"
KEY = os.getenv("OPENALEX_API_KEY")
WORK_FIELDS = "id,doi,authorships,primary_location"
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
    """Return {pmid: openalex_work}. Bulk lookup by DOI, then PMID for the rest."""
    found = {}
    bulk = [p for p in papers if p["doi"] and not any(c in p["doi"] for c in ",|")]
    for i in range(0, len(bulk), 50):                 # max 50 DOIs per request
        chunk = bulk[i:i + 50]
        data = _get("works", filter="doi:" + "|".join(p["doi"] for p in chunk),
                    per_page=50, select=WORK_FIELDS)
        by_doi = {_clean_doi(w["doi"]): w for w in data["results"] if w.get("doi")}
        for p in chunk:
            if p["doi"] in by_doi:
                found[p["pmid"]] = by_doi[p["doi"]]

    for p in papers:                                  # fallback: single PMID lookups (free)
        if p["pmid"] not in found:
            w = _get(f"works/pmid:{p['pmid']}", select=WORK_FIELDS)
            if w:
                found[p["pmid"]] = w
    return found


# ---------- Author and journal metrics (cached within a run) ----------
def author_info(aid):
    if aid not in _author_cache:
        a = _get(f"authors/{aid}", select="id,display_name,summary_stats") or {}
        _author_cache[aid] = {
            "id": aid,
            "name": a.get("display_name", "?"),
            "h": (a.get("summary_stats") or {}).get("h_index") or 0,
        }
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


def enrich(papers):
    """Add OpenAlex author/journal metrics to each paper dict (in place)."""
    works = _lookup_works(papers)
    for p in papers:
        w = works.get(p["pmid"])
        p["oa_matched"] = w is not None
        if not w:
            continue
        all_auths = w.get("authorships", [])       # unfiltered, so positions line up with PubMed
        auths = [a for a in all_auths if _author_id(a)]
        p["author_ids"] = [_author_id(a) for a in auths]
        p["author_names"] = [a["author"].get("display_name", "") for a in auths]

        # h-index lookups only for the key authors (the highest one counts):
        #   lead:           co-first authors flagged in PubMed, else the first author
        #   corresponding:  corresponding authors flagged in OpenAlex, else the last author (usually the PI)
        firsts = [a for a in (_find_authorship(all_auths, pos, last) for pos, last in p.get("co_first", []))
                  if a and _author_id(a)]
        firsts = firsts or [a for a in auths if a.get("author_position") == "first"]
        corrs = ([a for a in auths if a.get("is_corresponding")]
                 or [a for a in auths if a.get("author_position") == "last"])

        roles = {}                                 # author ID -> e.g. ["first", "corresponding"]
        for a in firsts:
            roles.setdefault(_author_id(a), []).append("co-first" if len(firsts) > 1 else "first")
        for a in corrs:
            roles.setdefault(_author_id(a), []).append("corresponding" if a.get("is_corresponding") else "last")
        # Copy the cached author dicts so the per-paper role isn't shared between papers
        p["key_authors"] = [{**author_info(aid), "role": "+".join(r)} for aid, r in roles.items()]
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