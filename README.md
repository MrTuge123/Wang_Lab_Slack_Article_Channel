## This is the working repo of a Slack-based information retrieval pipeline

## Code layout

```
main.py                 entry point: loops over subscribers, runs the steps below
digest/config.py        loads config.yaml + subscribers/*.yaml
digest/pubmed.py        search PubMed, fetch paper details
digest/openalex.py      author h-index, journal citedness  (python -m digest.openalex "Author Name")
digest/ranking.py       score, filter, sort
digest/summarizer.py    Kimi summaries
digest/notify/          slack.py, wecom.py (one module per chat; email goes here next)
digest/store.py         seen/ files and the run lock  (python -m digest.store merge FROM INTO)
```

## Subscribers

Each subscriber (a lab or channel) is one file in `subscribers/`, with its own query, filters, keywords and chats. The file name is its ID: `subscribers/wang_lab.yaml` → `seen/wang_lab.json` (papers it has already received). Shared defaults live in `config.yaml`; a subscriber's file overrides any of them.

**Add a subscriber**
1. Copy `subscribers/_template.yaml` to `subscribers/<name>.yaml` and fill in `query`, `ranking.key_words` and `outputs`.
2. For each chat switched on, add its webhook URL as a secret named as in `webhook_env`: in `.env` for local runs, and on GitHub under Settings → Secrets and variables → Actions. The workflow doesn't need editing.
3. Check it: `python main.py --subscriber <name> --dry-run`, then commit and push.

**Remove one:** delete its YAML file (or rename it to start with `_` to pause it).

**Run:** `python main.py` (everyone), `--subscriber <name>` (just one), `--dry-run` (print, don't post or save). On GitHub, "Run workflow" takes an optional subscriber name.

## Current Pipeline

For each subscriber in turn (one failing doesn't stop the others):

1. **Load settings:** `config.yaml` defaults + `subscribers/<name>.yaml`, and `.env` (webhook URLs, Kimi, NCBI and OpenAlex keys).
2. **Search PubMed:** up to k = 50 papers matching the query, added in the last n = 30 days, sorted by PubMed Best Match. The `journals:` whitelist is applied here if set.
3. **Drop seen papers:** skip any PMID or DOI already in `seen/<name>.json` (locally, the copy on GitHub is checked too).
4. **Fetch details:** title, journal, abstract, DOI, authors, and author keywords for each paper from PubMed.
5. **Enrich via OpenAlex:** find each paper by DOI (falling back to PMID), then look up the h-index of the key authors and keep the highest: co-first authors (PubMed's equal-contribution flags, else the first author) and corresponding authors (OpenAlex, else the last author). Also look up the journal's 2-year mean citedness. Papers not in OpenAlex yet get a neutral score.
6. **Score:** `0.6 × author score + 0.4 × journal score`, each capped at 1. Preferred authors or journals get full marks on that part. Then add `keyword_credit` (0.1) for each of the subscriber's `key_words` found in the paper's author keywords.
7. **Filter:** apply `min_score`, `min_author_h_index`, `min_journal_citedness`, and `keep_unmatched`. All are currently off, and preferred authors and journals always pass. The ranking table is printed here.
8. **Keep the top s = 5.**
9. **Summarize with Kimi:** a 2–3 sentence summary per paper, retrying with waits on rate limits. A paper going to several subscribers is summarized once.
10. **Post:** one digest with title, link, journal, top author and h-index, matched keywords, score, and summary, sent to every chat switched on under the subscriber's `outputs:` (Slack, WeCom; email is reserved and not built yet). WeCom gets it in as few messages as fit its 4096-byte limit. If one chat fails, the other still gets the digest. With `--dry-run`, it prints them instead.
11. **Save:** add the posted papers' PMIDs and DOIs to `seen/<name>.json` (if at least one chat got them).

Only one run at a time can go in a folder, and `seen/` files are written atomically. On GitHub, the save step merges `seen/` with anything pushed during the run.


## TODO:
1. ranking algorithm (similarity PubMed), authors ranking, journals (impact factor DB, csv)
2. scihub
3. Interactive API?