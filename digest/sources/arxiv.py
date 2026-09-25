"""arXiv preprints. Query syntax: https://info.arxiv.org/help/api/user-manual.html#query_details
e.g.  abs:"graph neural network" AND abs:"knowledge graph"   (fields: ti, abs, au, cat, all)
"""
import datetime as dt
import xml.etree.ElementTree as ET

import requests

from digest import paper

NAME = "arXiv"
URL = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def search(sub, query, since, limit):
    end = dt.date.today() + dt.timedelta(days=1)
    q = f"({query}) AND submittedDate:[{since:%Y%m%d}0000 TO {end:%Y%m%d}0000]"
    r = requests.get(URL, params={"search_query": q, "start": 0, "max_results": limit,
                                  "sortBy": "relevance", "sortOrder": "descending"}, timeout=60)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for e in root.findall("a:entry", NS):
        entry_id = e.findtext("a:id", "", NS)
        if "/api/errors" in entry_id:          # arXiv reports a bad query as an "error" entry
            raise RuntimeError(f"arXiv query error: {e.findtext('a:summary', '', NS).strip()}")
        doi = e.findtext("arxiv:doi", None, NS)        # set once it's published somewhere
        journal_ref = e.findtext("arxiv:journal_ref", None, NS)
        out.append(paper.new(
            NAME,
            arxiv_id=entry_id,
            title=e.findtext("a:title", "", NS),
            abstract=e.findtext("a:summary", "", NS),
            authors=[a.findtext("a:name", "", NS) for a in e.findall("a:author", NS)],
            journal=journal_ref or "arXiv (preprint)",
            doi=doi,
            url=entry_id,
            preprint=not doi,
        ))
    return out
