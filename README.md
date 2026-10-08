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
digest/relevance.py     Kimi scores each candidate's fit to the subscriber's interest (0-10, batched)
digest/ranking.py       score, filter, sort
digest/summarizer.py    Kimi summaries, overview, Chinese translations (batched)
digest/notify/          slack.py, wecom.py, mail.py (one module per chat)
digest/store.py         seen/ files and the run lock  (python -m digest.store merge FROM INTO)
digest/history.py       history/ files: every ranked candidate  (python -m digest.history merge FROM INTO)
```

## Subscribers

Each subscriber (a lab or channel) is one file in `subscribers/`, with its own query, filters, keywords and chats. The file name is its ID: `subscribers/wang_lab.yaml` → `seen/wang_lab.json` (papers it has already received). Shared defaults live in `config.yaml`; a subscriber's file overrides any of them.

**Add a subscriber**
1. Copy `subscribers/_template.yaml` to `subscribers/<name>.yaml` and fill in `query`, `ranking.key_words` and `outputs`.
2. For each chat switched on, add its webhook URL as a secret named as in `webhook_env`: in `.env` for local runs, and on GitHub under Settings → Secrets and variables → Actions. Also add the secret's name to the `env:` list of the Run digest step in `.github/workflows/digest.yml` (secrets are passed one by one).
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

### Chinese summaries

Add `chinese_summary: true` under any chat in a subscriber's `outputs:` to add a Simplified Chinese translation (中文概要) under each English summary, and under the digest's overview, in that chat only. Kimi translates the English summaries and overview, keeping gene/drug names and abbreviations as written: one extra Kimi call per digest, made only if some switched-on chat asks for it. If the translation fails, the digest goes out with the English summary alone. The Chinese text isn't saved to `history/`.

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
6. **Score relevance:** Kimi reads every candidate's title and abstract and scores 0–10 how well it fits the subscriber's interest (`interest:` if set, else `topic:`/`query:`, plus `key_words`), 25 papers per call (`relevance_batch`), answering without reasoning first (`relevance_thinking: false`: about 10 s for 50 papers instead of minutes, and steadier scores). Scores are saved in `history/` and reused in later runs while the interest, model and `relevance_thinking` are unchanged, so a paper that stays a candidate for several weeks is scored once. Set `relevance_weight: 0` to switch it off.
7. **Score:** weighted mix `1.0 × relevance + 0.6 × author score + 0.4 × journal score` (each 0–1, divided by the sum of the weights). Preprints get `preprint_journal_score` (0.3) for the journal part. Preferred authors or journals get full marks on that part. A paper Kimi couldn't score for relevance is scored on author and journal alone. Then add `keyword_credit` (0.1) for each of the subscriber's `key_words` found in the paper's title, abstract or author keywords.
8. **Filter:** apply `min_relevance` (0–10), `min_score`, `min_author_h_index`, `min_journal_citedness` (not for preprints), `keep_unmatched` and `keep_preprints`. The filters are currently off, and preferred authors and journals always pass. The ranking table (with which sources found each paper) is printed here.
9. **Keep the top s = 5.**
10. **Summarize with Kimi:** one call writes a 2–3 sentence summary of every paper plus a 3–5 sentence overview of the digest (no overview for a single paper), retrying with waits on rate limits. If the batched reply can't be used, the papers it missed get one call each. A paper going to several subscribers with the same interest is summarized once. One more call translates everything into Chinese if a chat asks for it.
11. **Connections:** compare the posted papers' reference lists (from OpenAlex, fetched in step 5's lookup) with the papers in `history/`: references they share with earlier papers (leaving out ones most of history cites, like GSEA or TCGA) and direct citations of earlier papers, sent or not. Shown at the end of the digest when there are any; no Kimi calls. Settings under `connections:` in `config.yaml`.
12. **Post:** one digest that opens with the same header in every chat ("<name> · paper digest", the dates searched, and "5 new papers, picked from 48 candidates") and the overview, then for each paper its title, link (PubMed, else DOI, else arXiv), journal, top author and h-index, matched keywords, relevance, score, and summary (plus a Chinese translation for chats with `chinese_summary: true`), sent to every chat switched on under the subscriber's `outputs:` (Slack, WeCom, email). WeCom gets it in as few messages as fit its 4096-byte limit. If one chat fails, the other still gets the digest. With `--dry-run`, it prints them instead.
13. **Save:** add all of the posted papers' IDs (PMID, DOI, arXiv ID, title) to `seen/<name>.json` (if at least one chat got them). Every ranked candidate, posted or not, also goes to `history/<name>.jsonl` (one paper per line, with its score, relevance, rank, journal citedness, key authors' h-index, keywords, abstract and summary) for trend summaries. A paper already there (any shared ID) updates its line instead of being added again; `first_seen`, `last_seen` and `posted_at` record when.

Only one run at a time can go in a folder, and `seen/` files are written atomically. On GitHub, the save step merges `seen/` and `history/` with anything pushed during the run. `.gitattributes` lets `git pull` merge `history/` files line by line instead of stopping with a conflict.

**Check a subscriber's sources** without ranking or posting: `python -m digest.sources <name>` lists what each source found and the merged papers.


## TODO:
1. ranking algorithm (similarity to lab papers), authors ranking, journals (impact factor DB, csv)
2. scihub
3. Interactive API?