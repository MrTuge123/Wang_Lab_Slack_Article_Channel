"""OpenAlex helpers: look up authors' h-index and journals' citation impact.

Also a tool to find an author's OpenAlex ID (names are ambiguous, IDs aren't):
    python openalex.py "Meng Wang"
"""
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()
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
        auths = [a for a in w.get("authorships", []) if (a.get("author") or {}).get("id")]
        p["author_ids"] = [_short(a["author"]["id"]) for a in auths]
        p["author_names"] = [a["author"].get("display_name", "") for a in auths]

        # Only first + last author get h-index lookups (lead + usually the PI)
        key = [_short(a["author"]["id"]) for a in auths
               if a.get("author_position") in ("first", "last")]
        infos = [author_info(aid) for aid in key]
        p["top_author"] = max(infos, key=lambda x: x["h"], default=None)

        src = (w.get("primary_location") or {}).get("source") or {}
        p["source"] = source_info(_short(src["id"])) if src.get("id") else None


# ---------- CLI: find an author's ID ----------
if __name__ == "__main__":
    name = " ".join(sys.argv[1:])
    if not name:
        sys.exit('Usage: python openalex.py "Author Name"')
    data = _get("authors", search=name, per_page=10,
                select="id,display_name,summary_stats,works_count,last_known_institutions")
    for a in data["results"]:
        inst = ", ".join(i["display_name"] for i in a.get("last_known_institutions") or [])
        h = (a.get("summary_stats") or {}).get("h_index", 0)
        print(f"{_short(a['id']):<13} h={h:<4} works={a['works_count']:<5} "
              f"{a['display_name']}  |  {inst}")