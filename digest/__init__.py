"""Paper digest: find new papers, rank them, summarize them, post them to each subscriber's chats.

    config.py      load config.yaml + subscribers/*.yaml
    paper.py       one paper record: IDs, link, merging duplicates
    sources/       PubMed, Europe PMC, OpenAlex, Semantic Scholar, arXiv (+ search_all)
    openalex.py    author h-index and journal citedness (+ author-ID lookup CLI)
    ranking.py     score, filter and sort papers
    query.py       one boolean query (or a topic Kimi turns into one) -> each source's syntax
    llm.py         Kimi client with rate-limit retries
    summarizer.py  2-3 sentence summaries with Kimi
    notify/        build and send the digest to Slack / WeCom
    store.py       what each subscriber has already received (seen/), run lock
"""
from dotenv import load_dotenv

load_dotenv()      # before any module reads API keys from the environment
