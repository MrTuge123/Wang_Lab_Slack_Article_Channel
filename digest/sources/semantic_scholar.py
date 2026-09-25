"""Semantic Scholar paper search (strong CS/AI coverage). Plain keywords, no AND/OR:
e.g.  graph neural network knowledge graph
Without SEMANTIC_SCHOLAR_API_KEY it shares a public rate limit and is often refused (retried a few times)."""
import datetime as dt
import os
import time

import requests

from digest import paper

NAME = "Semantic Scholar"
URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,abstract,authors,externalIds,venue,journal,publicationDate,publicationTypes,url"
PREPRINT_VENUES = ("arxiv", "biorxiv", "medrxiv", "ssrn", "research square", "preprints")


def search(sub, query, since, limit):
    key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    headers = {"x-api-key": key} if key else {}
    params = {"query": query, "fields": FIELDS, "limit": min(limit, 100),
              "publicationDateOrYear": f"{since.isoformat()}:{dt.date.today().isoformat()}"}
    for attempt in range(4):
        r = requests.get(URL, params=params, headers=headers, timeout=60)
        if r.status_code == 429 and attempt < 3:        # rate limited: wait 5, 10, 20 s
            time.sleep(5 * 2 ** attempt)
            continue
        r.raise_for_status()
        break
    out = []
    for x in r.json().get("data") or []:
        ext = x.get("externalIds") or {}
        venue = (x.get("journal") or {}).get("name") or x.get("venue") or ""
        preprint = not venue or any(v in venue.lower() for v in PREPRINT_VENUES)
        out.append(paper.new(
            NAME,
            title=x.get("title"),
            abstract=x.get("abstract"),
            authors=[a.get("name") for a in x.get("authors") or []],
            journal=f"{venue or 'Preprint'} (preprint)" if preprint else venue,
            doi=ext.get("DOI"),
            pmid=ext.get("PubMed"),
            arxiv_id=ext.get("ArXiv"),
            url=x.get("url"),
            preprint=preprint,
        ))
    return out
