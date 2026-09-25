"""Search PubMed for new papers and fetch their details (NCBI E-utilities)."""
import os
import xml.etree.ElementTree as ET

import requests

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _key():
    return os.getenv("NCBI_API_KEY")     # optional; raises limit to 10 req/sec


def build_query(sub):
    q = f"({sub['query']})"
    journals = sub.get("journals") or []
    if journals:
        q += " AND (" + " OR ".join(f'"{j}"[Journal]' for j in journals) + ")"
    return q


def search(sub):
    """PMIDs of papers matching the subscriber's query, added in the last days_back days."""
    r = requests.get(f"{EUTILS}/esearch.fcgi", params={
        "db": "pubmed",
        "term": build_query(sub),
        "reldate": sub["days_back"],
        "datetype": "edat",          # date the paper was added to PubMed
        "retmax": sub.get("candidate_pool", 50),
        "sort": sub.get("pubmed_sort", "relevance"),
        "retmode": "json",
        "api_key": _key(),
    }, timeout=30)
    r.raise_for_status()
    return r.json()["esearchresult"]["idlist"]


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
    """One paper dict per PMID: pmid, doi, title, journal, abstract, pubmed_authors, co_first, keywords."""
    r = requests.get(f"{EUTILS}/efetch.fcgi", params={
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
        papers.append({
            "pmid": art.findtext(".//PMID"),
            "doi": doi_el.text.strip().lower() if doi_el is not None and doi_el.text else None,
            "title": "".join(title_el.itertext()) if title_el is not None else "(no title)",
            "journal": art.findtext(".//Journal/Title") or "",
            "abstract": " ".join("".join(a.itertext())
                                 for a in art.findall(".//AbstractText")),
            "pubmed_authors": [f"{a.findtext('ForeName', '')} {a.findtext('LastName', '')}".strip()
                               for a in authors],
            "co_first": co_first_authors(authors),
            "keywords": ["".join(k.itertext()).strip() for k in art.findall(".//KeywordList/Keyword")],
        })
    return papers


def url(p):
    return f"https://pubmed.ncbi.nlm.nih.gov/{p['pmid']}/"
