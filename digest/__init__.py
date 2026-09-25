"""Paper digest: find new papers, rank them, summarize them, post them to each subscriber's chats.

    config.py      load config.yaml + subscribers/*.yaml
    pubmed.py      search PubMed and fetch paper details
    openalex.py    author h-index and journal citedness (+ author-ID lookup CLI)
    ranking.py     score, filter and sort papers
    summarizer.py  2-3 sentence summaries with Kimi
    notify/        build and send the digest to Slack / WeCom
    store.py       what each subscriber has already received (seen/), run lock
"""
from dotenv import load_dotenv

load_dotenv()      # before any module reads API keys from the environment
