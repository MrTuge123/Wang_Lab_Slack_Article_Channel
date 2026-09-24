"""Fetch new PubMed papers, summarize with Kimi, post to Slack.

Run:          python main.py
Test only:    python main.py --dry-run   (prints instead of posting)
"""
import json
import os
import sys
import xml.etree.ElementTree as ET

import requests
import yaml
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
CFG = yaml.safe_load(open("config.yaml"))
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
        "retmax": CFG["max_papers"],
        "sort": "pub_date",
        "retmode": "json",
        "api_key": NCBI_KEY,
    }, timeout=30)
    r.raise_for_status()
    return r.json()["esearchresult"]["idlist"]


def fetch_details(pmids):
    r = requests.get(f"{EUTILS}/efetch.fcgi", params={
        "db": "pubmed", "id": ",".join(pmids), "retmode": "xml",
        "api_key": NCBI_KEY,
    }, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)

    papers = []
    for art in root.findall(".//PubmedArticle"):
        title_el = art.find(".//ArticleTitle")
        papers.append({
            "pmid": art.findtext(".//PMID"),
            "title": "".join(title_el.itertext()) if title_el is not None else "(no title)",
            "journal": art.findtext(".//Journal/Title") or "",
            "abstract": " ".join("".join(a.itertext())
                                 for a in art.findall(".//AbstractText")),
        })
    return papers


# ---------- 2. Summarize with Kimi ----------
def summarize(paper):
    if not paper["abstract"]:
        return "_No abstract available._"
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


# ---------- 3. Post to Slack ----------
def esc(text):
    """Escape characters Slack treats specially."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def post_to_slack(text):
    if DRY_RUN:
        print("\n----- DRY RUN: would post -----\n" + text)
        return
    r = requests.post(os.environ["SLACK_WEBHOOK_URL"], json={"text": text}, timeout=30)
    r.raise_for_status()


# ---------- Remember what's already been posted ----------
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

    papers = fetch_details(pmids)
    lines = [f":newspaper: *New papers* for `{esc(CFG['query'])}` "
             f"(last {CFG['days_back']} days)\n"]
    for p in papers:
        print("Summarizing:", p["title"][:80])
        url = f"https://pubmed.ncbi.nlm.nih.gov/{p['pmid']}/"
        lines.append(f"*<{url}|{esc(p['title'])}>*\n"
                     f"_{esc(p['journal'])}_\n"
                     f"{esc(summarize(p))}\n")

    post_to_slack("\n".join(lines))
    if not DRY_RUN:
        save_seen(seen | set(pmids))
    print(f"Done: {len(papers)} papers.")


if __name__ == "__main__":
    main()