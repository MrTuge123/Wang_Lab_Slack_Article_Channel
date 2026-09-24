## This is the working repo of a Slack-based information retrieval pipeline

## Current Pipeline

1. **Load settings:** `config.yaml` (query, n/k/s, ranking weights and filters) and `.env` (Slack, Kimi, NCBI, and OpenAlex keys).
2. **Search PubMed:** up to k = 50 papers matching the query, added in the last n = 7 days, sorted by PubMed Best Match. The `journals:` whitelist is applied here if set.
3. **Drop seen papers:** skip any PMID or DOI already in `seen.json`.
4. **Fetch details:** title, journal, abstract, DOI, and authors for each paper from PubMed.
5. **Enrich via OpenAlex:** find each paper by DOI (falling back to PMID), then look up the higher h-index of the first and last authors and the journal's 2-year mean citedness. Papers not in OpenAlex yet get a neutral score.
6. **Score:** `0.6 × author score + 0.4 × journal score`, each capped at 1. Preferred authors or journals get full marks on that part.
7. **Filter:** apply `min_score`, `min_author_h_index`, `min_journal_citedness`, and `keep_unmatched`. All are currently off, and preferred authors and journals always pass. The ranking table is printed here.
8. **Keep the top s = 5.**
9. **Summarize with Kimi:** a 2–3 sentence summary per paper, retrying with waits on rate limits.
10. **Post to Slack:** one digest message with title, link, journal, top author and h-index, score, and summary. With `--dry-run`, it prints instead.
11. **Save:** add the posted papers' PMIDs and DOIs to `seen.json`.


## TODO:
1. ranking algorithm (similarity PubMed), authors ranking, journals (impact factor DB, csv)
2. scihub
3. Interactive API?