"""For each subscriber: search PubMed, Europe PMC, OpenAlex, Semantic Scholar and arXiv for new
papers, merge duplicates, rank them by author/journal impact (OpenAlex),
summarize the top ones with Kimi, and post to that subscriber's Slack / WeCom.
The steps live in digest/ (see digest/__init__.py for the map).

Subscribers:   one file each in subscribers/ (copy subscribers/_template.yaml)
Shared config: config.yaml (defaults; a subscriber's file overrides them)
Already sent:  seen/<subscriber>.json
All ranked:    history/<subscriber>.jsonl (every candidate with its score, for trend summaries)

Run all:          python main.py
One subscriber:   python main.py --subscriber wang_lab
Test only:        python main.py --dry-run   (prints ranking + messages, doesn't post or save)
"""
import argparse
import sys
import traceback

import requests

from digest import notify, openalex, paper, ranking, sources, summarizer
from digest.config import load_subscribers
from digest.history import save_history
from digest.store import load_seen, run_lock, save_seen


def run_subscriber(sub, dry_run=False):
    """The whole digest for one subscriber. Returns the chats that failed (empty if none)."""
    print(f"\n========== {sub['name']} ({sub['id']}) ==========")
    seen = load_seen(sub["id"])
    papers, report = sources.search_all(sub)
    print("Found:", sources.describe(report))
    papers = [p for p in papers if not paper.ids(p) & seen]      # any shared ID = already sent
    if not papers:
        print("No new papers found.")
        return []
    print(f"{len(papers)} new candidates. Looking up authors/journals in OpenAlex...")
    try:
        openalex.enrich(papers)
    except requests.RequestException as e:
        print(f"Warning: OpenAlex lookup failed ({e}); ranking without it.")

    papers = ranking.rank_papers(papers, sub["ranking"])
    ranking.print_ranking(papers)
    top = [p for p in papers if p["passed"]][:sub["max_papers"]]
    if not top:
        print("No papers passed the filters.")
        if not dry_run:
            save_history(sub["id"], papers, posted=[])
        return []

    for p in top:                           # once, shared by every chat
        print("Summarizing:", p["title"][:80])
        p["summary"] = summarizer.summarize(p, sub["model"])

    posted, failed = notify.post(top, sub, dry_run, {"candidates": len(papers), "found": report})
    if posted:                              # at least one chat has them, so don't post them again
        if not dry_run:
            save_seen(sub["id"], set().union(*(paper.ids(p) for p in top)))
        print(f"Done: posted {len(top)} of {len(papers)} candidates to {' and '.join(posted)}.")
    if not dry_run:                         # every ranked candidate, for trend summaries
        save_history(sub["id"], papers, posted=top if posted else [])
    return failed


def main():
    ap = argparse.ArgumentParser(description="Post new-paper digests to each subscriber's chats.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the ranking and messages; don't post or save")
    ap.add_argument("--subscriber", metavar="NAME",
                    help="run only this subscriber (its file name in subscribers/, without .yaml)")
    args = ap.parse_args()

    failures = []
    for sub in load_subscribers(args.subscriber):
        try:
            failed = run_subscriber(sub, args.dry_run)
        except Exception as e:              # one subscriber's problem shouldn't stop the others
            traceback.print_exc()
            print(f"Error: {sub['id']} failed ({e})")
            failed = ["run"]
        failures += [f"{sub['id']} ({name})" for name in failed]
    if failures:
        sys.exit("Failed: " + ", ".join(failures))


if __name__ == "__main__":
    with run_lock():                        # one run at a time in this folder
        main()
