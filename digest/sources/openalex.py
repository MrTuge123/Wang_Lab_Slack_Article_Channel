"""OpenAlex works search: journals, conferences and preprints across all fields.
Query syntax: words or "phrases" combined with AND / OR / NOT (upper case).
Filtered to papers published in the last days_back days."""
import datetime as dt
import re

from digest import openalex as oa
from digest import paper

NAME = "OpenAlex"
FIELDS = oa.WORK_FIELDS + ",display_name,ids,abstract_inverted_index"


def abstract_from_index(inv):
    """OpenAlex stores abstracts as {word: [positions]}; rebuild the text."""
    if not inv:
        return ""
    words = sorted((pos, w) for w, positions in inv.items() for pos in positions)
    return " ".join(w for _, w in words)


def search(sub, query, since, limit):
    data = oa._get("works", search=query, per_page=min(limit, 200), select=FIELDS,
                   filter=f"from_publication_date:{since.isoformat()},"
                          f"to_publication_date:{dt.date.today().isoformat()}")
    out = []
    for w in (data or {}).get("results", []):
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        preprint = w.get("type") == "preprint" or src.get("type") == "repository"
        journal = src.get("display_name") or ""
        if preprint:                            # "arXiv (Cornell University)" -> "arXiv (preprint)"
            journal = f"{re.sub(r' [(].*[)]$', '', journal) or 'Preprint'} (preprint)"
        doi = paper.norm_doi(w.get("doi"))
        arxiv_id = doi[len(paper.ARXIV_DOI_PREFIX):] if doi and doi.startswith(paper.ARXIV_DOI_PREFIX) else None
        p = paper.new(
            NAME,
            title=w.get("display_name"),
            abstract=abstract_from_index(w.get("abstract_inverted_index")),
            authors=[(a.get("author") or {}).get("display_name") for a in w.get("authorships") or []],
            journal=journal,
            doi=doi,
            pmid=oa._short((w.get("ids") or {}).get("pmid")),
            arxiv_id=arxiv_id,
            openalex_id=oa._short(w.get("id")),
            url=loc.get("landing_page_url") or w.get("id"),
            keywords=[k.get("display_name") for k in w.get("keywords") or []],
            preprint=preprint,
        )
        p["oa_work"] = w                        # enrichment reuses it instead of looking it up again
        out.append(p)
    return out
