"""Fetch new PubMed papers, rank them by author/journal impact (OpenAlex),
summarize the top ones with Kimi, and post to Slack.

Run:          python main.py
Test only:    python main.py --dry-run   (prints ranking + message, doesn't post)
"""
import json
import os
import sys
import time
import xml.etree.ElementTree as ET

import requests
import yaml
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

import openalex

load_dotenv()
CFG = yaml.safe_load(open("config.yaml"))
RANK = CFG.get("ranking") or {}
DRY_RUN = "--dry-run" in sys.argv
SEEN_FILE = "seen.json"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_KEY = os.getenv("NCBI_API_KEY")   # optional; raises limit to 10 req/sec

kimi = OpenAI(base_url="https://api.moonshot.ai/v1",
              api_key=os.environ["MOONSHOT_API_KEY"])


# ---------- 1. Search PubMed ----------
def build_query():
    q = f"({CFG['query']})"
    journals = CFG.get("journals") or []
    if journals:
        q += " AND (" + " OR ".join(f'"{j}"[Journal]' for j in journals) + ")"
    return q


def search_pubmed():
    r = requests.get(f"{EUTILS}/esearch.fcgi", params={
        "db": "pubmed",
        "term": build_query(),
        "reldate": CFG["days_back"],
        "datetype": "edat",          # date the paper was added to PubMed
        "retmax": CFG.get("candidate_pool", 50),
        "sort": CFG.get("pubmed_sort", "relevance"),
        "retmode": "json",
        "api_key": NCBI_KEY,
    }, timeout=30)
    r.raise_for_status()
    return r.json()["esearchresult"]["idlist"]


def fetch_details(pmids):
    r = requests.get(f"{EUTILS}/efetch.fcgi", params={
        "db": "pubmed", "id": ",".join(pmids), "retmode": "xml",
        "api_key": NCBI_KEY,
    }, timeout=60)
    r.raise_for_status()
    root = ET.fromstring(r.content)

    papers = []
    for art in root.findall(".//PubmedArticle"):
        title_el = art.find(".//ArticleTitle")
        doi_el = art.find(".//PubmedData/ArticleIdList/ArticleId[@IdType='doi']")
        papers.append({
            "pmid": art.findtext(".//PMID"),
            "doi": doi_el.text.strip().lower() if doi_el is not None and doi_el.text else None,
            "title": "".join(title_el.itertext()) if title_el is not None else "(no title)",
            "journal": art.findtext(".//Journal/Title") or "",
            "abstract": " ".join("".join(a.itertext())
                                 for a in art.findall(".//AbstractText")),
            "pubmed_authors": [f"{a.findtext('ForeName', '')} {a.findtext('LastName', '')}".strip()
                               for a in art.findall(".//AuthorList/Author")],
        })
    return papers


# ---------- 2. Rank with author / journal impact ----------
def _norm(s):
    return s.strip().lower()


def is_preferred_author(p):
    prefs = {_norm(a) for a in RANK.get("preferred_authors") or []}
    ids = {_norm(i) for i in p.get("author_ids", [])}
    names = {_norm(n) for n in p.get("author_names", []) + p["pubmed_authors"]}
    return bool(prefs & (ids | names))


def is_preferred_journal(p):
    prefs = {_norm(j) for j in RANK.get("preferred_journals") or []}
    names = {_norm(p["journal"])}
    if p.get("source"):
        names.add(_norm(p["source"]["name"]))
    return bool(prefs & names)


def author_h(p):
    return p["top_author"]["h"] if p.get("top_author") else 0


def journal_citedness(p):
    return p["source"]["citedness"] if p.get("source") else 0


def score(p):
    wa, wj = RANK.get("author_weight", 0.6), RANK.get("journal_weight", 0.4)
    if p.get("oa_matched"):
        a = min(author_h(p) / RANK.get("author_h_cap", 60), 1)
        j = min(journal_citedness(p) / RANK.get("journal_citedness_cap", 10), 1)
    else:
        a = j = RANK.get("unmatched_score", 0.3)
    if is_preferred_author(p):
        a = 1.0
    if is_preferred_journal(p):
        j = 1.0
    return round((wa * a + wj * j) / (wa + wj), 3)


def passes_filters(p):
    if is_preferred_author(p) or is_preferred_journal(p):
        return True
    if p["score"] < RANK.get("min_score", 0):
        return False
    if not p.get("oa_matched"):
        return RANK.get("keep_unmatched", True)
    return (author_h(p) >= RANK.get("min_author_h_index", 0)
            and journal_citedness(p) >= RANK.get("min_journal_citedness", 0))


def print_ranking(papers):
    print(f"\n{'score':>5}  {'h':>4}  {'jrnl':>5}  pass  title")
    for p in papers:
        flag = "yes" if p["passed"] else "no"
        tag = "" if p.get("oa_matched") else " [not in OpenAlex]"
        print(f"{p['score']:>5.2f}  {author_h(p):>4}  {journal_citedness(p):>5}  "
              f"{flag:<4}  {p['title'][:60]}{tag}")
    print()


# ---------- 3. Summarize with Kimi ----------
def summarize(paper):
    if not paper["abstract"]:
        return "_No abstract available._"
    for attempt in range(5):                # new Kimi accounts allow only 3 requests/min
        try:
            return _summarize_once(paper)
        except RateLimitError:
            wait = 20 * (attempt + 1)
            print(f"  Kimi rate limit hit, waiting {wait}s...")
            time.sleep(wait)
    return "_Summary unavailable (rate limited)._"


def _summarize_once(paper):
    r = kimi.chat.completions.create(
        model=CFG["model"],
        messages=[
            {"role": "system", "content":
                "You summarize scientific papers for a research lab's Slack "
                "channel. Be accurate, concise, and don't invent details."},
            {"role": "user", "content":
                f"Title: {paper['title']}\n\nAbstract: {paper['abstract']}\n\n"
                "Write a 2-3 sentence plain-English summary: what they did "
                "and the key finding."},
        ],
    )
    return r.choices[0].message.content.strip()


# ---------- 4. Post to Slack ----------
def esc(text):
    """Escape characters Slack treats specially."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def impact_line(p):
    bits = [esc(p["journal"])]
    if p.get("top_author"):
        bits.append(f"top author: {esc(p['top_author']['name'])} (h={p['top_author']['h']})")
    bits.append(f"score {p['score']:.2f}")
    return "_" + " · ".join(bits) + "_"


def post_to_slack(text):
    if DRY_RUN:
        print("----- DRY RUN: would post -----\n" + text)
        return
    r = requests.post(os.environ["SLACK_WEBHOOK_URL"], json={"text": text}, timeout=30)
    r.raise_for_status()


# ---------- Remember what's already been posted (DOIs and PMIDs) ----------
def load_seen():
    if os.path.exists(SEEN_FILE):
        return set(json.load(open(SEEN_FILE)))
    return set()


def save_seen(seen):
    json.dump(sorted(seen), open(SEEN_FILE, "w"), indent=1)


# ---------- Main ----------
def main():
    seen = load_seen()
    pmids = [p for p in search_pubmed() if p not in seen]
    if not pmids:
        print("No new papers found.")
        return

    papers = [p for p in fetch_details(pmids) if p["doi"] not in seen]
    print(f"{len(papers)} new candidates. Looking up authors/journals in OpenAlex...")
    try:
        openalex.enrich(papers)
    except requests.RequestException as e:
        print(f"Warning: OpenAlex lookup failed ({e}); ranking without it.")

    for p in papers:
        p["score"] = score(p)
        p["passed"] = passes_filters(p)
    papers.sort(key=lambda p: p["score"], reverse=True)
    print_ranking(papers)

    top = [p for p in papers if p["passed"]][:CFG["max_papers"]]
    if not top:
        print("No papers passed the filters.")
        return

    lines = [f":newspaper: *New papers* for `{esc(CFG['query'])}` "
             f"(last {CFG['days_back']} days)\n"]
    for p in top:
        print("Summarizing:", p["title"][:80])
        url = f"https://pubmed.ncbi.nlm.nih.gov/{p['pmid']}/"
        lines.append(f"*<{url}|{esc(p['title'])}>*\n"
                     f"{impact_line(p)}\n"
                     f"{esc(summarize(p))}\n")

    post_to_slack("\n".join(lines))
    if not DRY_RUN:
        save_seen(seen | {p["pmid"] for p in top} | {p["doi"] for p in top if p["doi"]})
    print(f"Done: posted {len(top)} of {len(papers)} candidates.")


if __name__ == "__main__":
    main()