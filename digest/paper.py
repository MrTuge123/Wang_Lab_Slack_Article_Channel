"""One paper, whichever source found it, and merging the same paper found by several sources.

A paper is a dict made by new(). Its IDs (PMID, DOI, arXiv ID, normalized title) decide
whether two records are the same paper, and are what seen/<subscriber>.json remembers.
"""
import html
import re

ARXIV_DOI_PREFIX = "10.48550/arxiv."          # DataCite DOIs arXiv gives every preprint
MIN_TITLE_KEY = 30                            # shorter titles are too generic to match papers on


def norm_doi(doi):
    """'https://doi.org/10.1/ABC' -> '10.1/abc'"""
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", d)
    return d or None


def norm_arxiv(aid):
    """'http://arxiv.org/abs/2409.01234v2', 'arXiv:2409.01234' -> '2409.01234'"""
    if not aid:
        return None
    a = re.sub(r"^(https?://(export\.)?arxiv\.org/(abs|pdf)/|arxiv:)", "", aid.strip(), flags=re.I)
    return re.sub(r"v\d+$", "", a) or None


def clean_text(s):
    """Drop HTML/XML tags and entities, collapse whitespace."""
    if not s:
        return ""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def norm_title(title):
    return " ".join(re.findall(r"[a-z0-9]+", (title or "").lower()))


def new(source, title, abstract="", authors=(), journal="", doi=None, pmid=None, arxiv_id=None,
        openalex_id=None, url=None, keywords=(), co_first=(), preprint=False):
    """A paper record. `source` is the display name of the source that found it."""
    arxiv_id = norm_arxiv(arxiv_id)
    doi = norm_doi(doi)
    if not doi and arxiv_id:
        doi = ARXIV_DOI_PREFIX + arxiv_id     # lets OpenAlex find the preprint by DOI
    return {
        "sources": [source],
        "title": clean_text(title) or "(no title)",
        "abstract": clean_text(abstract),
        "authors": [a for a in authors if a],
        "journal": journal or "",
        "doi": doi,
        "pmid": str(pmid) if pmid else None,
        "arxiv_id": arxiv_id,
        "openalex_id": openalex_id,
        "link": url,
        "keywords": [k for k in keywords if k],
        "co_first": list(co_first),           # [(position, last name)], PubMed only
        "preprint": bool(preprint),
    }


def ids(p):
    """Every ID the paper is known by (also what seen files store)."""
    out = set()
    if p.get("pmid"):
        out.add(p["pmid"])
    if p.get("doi"):
        out.add(p["doi"])
    if p.get("arxiv_id"):
        out.add("arxiv:" + p["arxiv_id"])
    t = norm_title(p.get("title"))
    if len(t) >= MIN_TITLE_KEY:
        out.add("title:" + t)
    return out


def key(p):
    """One stable ID for the paper (for caches)."""
    for k in ("doi", "pmid"):
        if p.get(k):
            return p[k]
    if p.get("arxiv_id"):
        return "arxiv:" + p["arxiv_id"]
    return "title:" + norm_title(p["title"])


def url(p):
    """Best link: PubMed page, else the publisher DOI, else arXiv, else whatever the source gave."""
    if p.get("pmid"):
        return f"https://pubmed.ncbi.nlm.nih.gov/{p['pmid']}/"
    if p.get("doi") and not p["doi"].startswith(ARXIV_DOI_PREFIX):
        return f"https://doi.org/{p['doi']}"
    if p.get("arxiv_id"):
        return f"https://arxiv.org/abs/{p['arxiv_id']}"
    return p.get("link") or (f"https://doi.org/{p['doi']}" if p.get("doi") else "")


def links(p):
    """[(label, url)] for every place to read the paper, best first."""
    out = []
    if p.get("pmid"):
        out.append(("PubMed", f"https://pubmed.ncbi.nlm.nih.gov/{p['pmid']}/"))
    if p.get("doi") and not p["doi"].startswith(ARXIV_DOI_PREFIX):
        out.append(("Publisher", f"https://doi.org/{p['doi']}"))
    if p.get("arxiv_id"):
        out.append(("arXiv", f"https://arxiv.org/abs/{p['arxiv_id']}"))
    if not out and url(p):
        out.append(("Link", url(p)))
    return out


def _absorb(a, b):
    """Fill gaps in a with b's details. A published version (b) replaces a preprint (a)."""
    a["sources"] += [s for s in b["sources"] if s not in a["sources"]]
    if a["preprint"] and not b["preprint"]:
        a["preprint"] = False
        a["journal"] = b["journal"] or a["journal"]
        if b["doi"]:
            a["doi"] = b["doi"]
        a.pop("oa_work", None)                # OpenAlex record was for the preprint
    for f in ("doi", "pmid", "arxiv_id", "openalex_id", "link", "abstract", "journal"):
        if not a.get(f) and b.get(f):
            a[f] = b[f]
    for f in ("authors", "co_first"):
        if not a[f]:
            a[f] = b[f]
    if "oa_work" not in a and "oa_work" in b and a["preprint"] == b["preprint"]:
        a["oa_work"] = b["oa_work"]
    have = {k.lower() for k in a["keywords"]}
    a["keywords"] += [k for k in b["keywords"] if k.lower() not in have]


def merge(papers):
    """Merge records of the same paper (shared PMID, DOI, arXiv ID or title).
    Earlier records win on details, so pass papers in source-priority order."""
    merged, index = [], {}
    for p in papers:
        hit = next((index[i] for i in ids(p) if i in index), None)
        if hit is None:
            merged.append(p)
            hit = p
        else:
            _absorb(hit, p)
        for i in ids(hit) | ids(p):
            index[i] = hit
    return merged
