## This is the working repo of a Slack-based information retrieval pipeline

## Code layout

```
main.py                 entry point: loops over subscribers, runs the steps below
digest/config.py        loads config.yaml + subscribers/*.yaml
digest/paper.py         one paper record: IDs, link, merging duplicates
digest/sources/         pubmed, europepmc, openalex, semantic_scholar, arxiv  (python -m digest.sources <subscriber>)
digest/query.py         one query -> each source's syntax  (python -m digest.query '<query>' or --topic "...")
digest/llm.py           Kimi client with rate-limit retries
digest/openalex.py      author h-index, journal citedness  (python -m digest.openalex "Author Name")
digest/ranking.py       score, filter, sort
digest/summarizer.py    Kimi summaries
digest/notify/          slack.py, wecom.py, mail.py (one module per chat)
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

## Search queries

Write the search once per subscriber, in one of two ways:

- **`query:`** a boolean query: words or `"quoted phrases"`, `AND` / `OR` / `NOT` (upper case), parentheses; terms side by side are ANDed. It's translated into each source's syntax on every run (PubMed gets it as written; PubMed tags like `[tiab]` are dropped for other sources).
- **`topic:`** a plain-English description. Kimi writes a boolean query from it on every run (printed in the log), which is then translated the same way.

| Source | `"graph neural network" AND ("knowledge graph" OR KG) NOT review` becomes |
|---|---|
| PubMed, Europe PMC, OpenAlex | the same boolean query |
| arXiv | `abs:"graph neural network" AND (abs:"knowledge graph" OR abs:KG) ANDNOT abs:review` |
| Semantic Scholar | `graph neural network knowledge graph` (plain keywords: the first choice of each OR, no NOT terms) |

To hand-tune one source, give it its own `query:` under `sources:` in that source's syntax; it overrides the translation. Preview: `python -m digest.query '<query>'` or `python -m digest.query --topic "<topic>"`.

## Email

The digest can also go out by email from a Gmail account with an app password.

1. Sender account, as secrets (`.env` locally, GitHub → Settings → Secrets → Actions):
   `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER=literaturebot99@gmail.com`, `SMTP_PASSWORD=<app password>`.
2. Per subscriber, under `outputs:`:
   ```yaml
   email:
     enabled: true
     to: ["a@umich.edu"]        # or to_env: EMAIL_TO_WANG_LAB (a secret with comma-separated addresses)
   ```
   Recipients are Bcc'd. If the repository is public, prefer `to_env` so addresses aren't published.

## Current Pipeline

For each subscriber in turn (one failing doesn't stop the others):

1. **Load settings:** `config.yaml` defaults + `subscribers/<name>.yaml`, and `.env` (webhook URLs, Kimi, NCBI, OpenAlex and optional Semantic Scholar keys).
2. **Search every source switched on, in parallel:** each with the query translated into its syntax (see Search queries), up to k = 50 papers each from the last n = 30 days. If a source fails, the others still run.
   - **PubMed:** papers added in the window, sorted by Best Match; the `journals:` whitelist is applied in the query.
   - **Europe PMC:** PubMed plus bioRxiv/medRxiv preprints and more (by first publication date).
   - **OpenAlex:** journals, conferences and preprints in every field (by publication date).
   - **Semantic Scholar:** strong on CS/AI (plain keywords; set `SEMANTIC_SCHOLAR_API_KEY` to avoid rate limits).
   - **arXiv:** preprints submitted in the window.
3. **Merge duplicates:** records sharing a PMID, DOI, arXiv ID or title become one paper; a published version replaces its preprint. With a `journals:` whitelist, papers from other sources must match it (preprints are dropped).
4. **Drop seen papers:** skip any paper with an ID already in `seen/<name>.json` (locally, the copy on GitHub is checked too).
5. **Enrich via OpenAlex:** find each paper (reusing OpenAlex search results, else by DOI, PMID or OpenAlex ID), then look up the h-index of the key authors and keep the highest: co-first authors (PubMed's equal-contribution flags, else the first author) and corresponding authors (OpenAlex, else the last author). Also look up the journal's 2-year mean citedness, and fill in keywords for papers whose source had none. Papers not in OpenAlex yet get a neutral score.
6. **Score:** `0.6 × author score + 0.4 × journal score`, each capped at 1. Preprints get `preprint_journal_score` (0.3) for the journal part. Preferred authors or journals get full marks on that part. Then add `keyword_credit` (0.1) for each of the subscriber's `key_words` found in the paper's keywords.
7. **Filter:** apply `min_score`, `min_author_h_index`, `min_journal_citedness` (not for preprints), `keep_unmatched` and `keep_preprints`. The filters are currently off, and preferred authors and journals always pass. The ranking table (with which sources found each paper) is printed here.
8. **Keep the top s = 5.**
9. **Summarize with Kimi:** a 2–3 sentence summary per paper, retrying with waits on rate limits. A paper going to several subscribers is summarized once.
10. **Post:** one digest with title, link (PubMed, else DOI, else arXiv), journal, top author and h-index, matched keywords, score, and summary, sent to every chat switched on under the subscriber's `outputs:` (Slack, WeCom, email). WeCom gets it in as few messages as fit its 4096-byte limit. If one chat fails, the other still gets the digest. With `--dry-run`, it prints them instead.
11. **Save:** add all of the posted papers' IDs (PMID, DOI, arXiv ID, title) to `seen/<name>.json` (if at least one chat got them).

Only one run at a time can go in a folder, and `seen/` files are written atomically. On GitHub, the save step merges `seen/` with anything pushed during the run.

**Check a subscriber's sources** without ranking or posting: `python -m digest.sources <name>` lists what each source found and the merged papers.


## TODO:
1. ranking algorithm (similarity to query / lab papers), authors ranking, journals (impact factor DB, csv)
2. scihub
3. Interactive API?