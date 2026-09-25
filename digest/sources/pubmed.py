"""PubMed (NCBI E-utilities). Uses the subscriber's query: in PubMed search-box syntax,
restricted to papers added to PubMed in the last days_back days."""
import os
import xml.etree.ElementTree as ET

import requests

from digest import paper

NAME = "PubMed"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _key():
    return os.getenv("NCBI_API_KEY")     # optional; raises limit to 10 req/sec


def build_query(sub, query):
    q = f"({query})"
    journals = sub.get("journals") or []
    if journals:
        q += " AND (" + " OR ".join(f'"{j}"[Journal]' for j in journals) + ")"
    return q


def search(sub, query, since, limit):
    r = requests.get(f"{EUTILS}/esearch.fcgi", params={
        "db": "pubmed",
        "term": build_query(sub, query),
        "reldate": sub["days_back"],
        "datetype": "edat",          # date the paper was added to PubMed
        "retmax": limit,
        "sort": sub.get("pubmed_sort", "relevance"),
        "retmode": "json",
        "api_key": _key(),
    }, timeout=30)
    r.raise_for_status()
    pmids = r.json()["esearchresult"]["idlist"]
    return fetch_details(pmids) if pmids else []


def co_first_authors(authors):
    """[(position, last name)] of the authors PubMed marks as equal first authors.
    Only the run at the top of the list counts; flags further down usually mark co-senior authors."""
    run = []
    for i, a in enumerate(authors):
        if a.get("EqualContrib") != "Y":
            break
        run.append((i, a.findtext("LastName", "")))
    return run


def fetch_details(pmids):
    r = requests.post(f"{EUTILS}/efetch.fcgi", data={
        "db": "pubmed", "id": ",".join(pmids), "retmode": "xml",
        "api_key": _key(),
    }, timeout=60)
    r.raise_for_status()
    root = ET.fromstring(r.content)

    papers = []
    for art in root.findall(".//PubmedArticle"):
        title_el = art.find(".//ArticleTitle")
        doi_el = art.find(".//PubmedData/ArticleIdList/ArticleId[@IdType='doi']")
        authors = art.findall(".//AuthorList/Author")
        papers.append(paper.new(
            NAME,
            pmid=art.findtext(".//PMID"),
            doi=doi_el.text if doi_el is not None else None,
            title="".join(title_el.itertext()) if title_el is not None else "",
            journal=art.findtext(".//Journal/Title") or "",
            abstract=" ".join("".join(a.itertext()) for a in art.findall(".//AbstractText")),
            authors=[f"{a.findtext('ForeName', '')} {a.findtext('LastName', '')}".strip() for a in authors],
            co_first=co_first_authors(authors),
            keywords=["".join(k.itertext()).strip() for k in art.findall(".//KeywordList/Keyword")],
        ))
    return papers
