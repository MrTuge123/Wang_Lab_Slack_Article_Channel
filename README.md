## This is the working repo of a Slack-based information retrieval pipeline

### Stage 1: Fetch new papers
- PubMed E-utilities for journal retrieval
- Crossref API

### Stage 2: store, de-duplicate
- write seen.json (or SQLite) -> DOI (Fallback: PMID)

### Stage 3: summarize with LLM API
- Summarize with LLM API

### Post to Slack
- Create Slack app with an incoming Webhook

### Skills
- Keywords?
- Authors (weights)
- Daily
- Manual/Automatic?
- Use domain knowledge
- Target Scope, Target Journal
- email/slack auto plugin ()

Main questions now:
1. we need customizable features:
    1.1 journals (we want to be able to target specific )
    1.2 specific authors in topics might be weighed more, how do we determine what authors are 'authorities' in the field
2. pipeline should be:
    2.1. obtain the top k articles, sort by relevance using PubMed's built in algorithm published in the past n days, or we can also use keywords
    2.2 feed the abstract/title/keywords into LLM model, LLM scores each article's relevance (title, abstract, keywords) against a lab-interest profile; author weights come from a config list and/or OpenAlex/Semantic Scholar metrics
    2.3 for the determined articles, read the full journal article (availability TBA), summarize (metrics TBD) and return the top s results to slack
3. How to evaluate?
4. Potential learning from slack?
5. How to determine 'authorities'
     a manual list, metrics, or both, and how much weight they get
6. Parameters from part 2, n, k, s, adjustable?