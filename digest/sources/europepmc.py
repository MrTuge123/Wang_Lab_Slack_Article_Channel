"""Europe PMC: everything in PubMed plus preprints (bioRxiv, medRxiv, ...), PMC and more.
Query syntax: https://europepmc.org/searchsyntax  e.g.  "graph neural network" AND "knowledge graph"
"""
import datetime as dt

import requests

from digest import paper

NAME = "Europe PMC"
URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def search(sub, query, since, limit):
    # FIRST_PDATE = first publication date. Set sources.europepmc.date_field: FIRST_IDATE
    # to filter on the date Europe PMC indexed the paper instead.
    date_field = ((sub.get("sources") or {}).get("europepmc") or {}).get("date_field", "FIRST_PDATE")
    today = dt.date.today()
    q = f"({query}) AND {date_field}:[{since.isoformat()} TO {today.isoformat()}]"
    r = requests.get(URL, params={"query": q, "format": "json", "resultType": "core",
                                  "pageSize": min(limit, 1000)}, timeout=60)
    r.raise_for_status()
    out = []
    for x in (r.json().get("resultList") or {}).get("result", []):
        src = x.get("source")                  # MED = PubMed, PPR = preprint, PMC, AGR, ...
        preprint = src == "PPR"
        journal = (((x.get("journalInfo") or {}).get("journal") or {}).get("title")
                   or (x.get("bookOrReportDetails") or {}).get("publisher") or "")
        if preprint:
            journal = f"{journal or 'Preprint'} (preprint)"
        authors = [a.get("fullName") or f"{a.get('firstName', '')} {a.get('lastName', '')}".strip()
                   for a in (x.get("authorList") or {}).get("author", [])]
        out.append(paper.new(
            NAME,
            title=x.get("title"),
            abstract=x.get("abstractText"),
            authors=authors,
            journal=journal,
            doi=x.get("doi"),
            pmid=x.get("pmid"),
            url=f"https://europepmc.org/article/{src}/{x.get('id')}" if src and x.get("id") else None,
            keywords=(x.get("keywordList") or {}).get("keyword", []),
            preprint=preprint,
        ))
    return out
