"""2-3 sentence plain-English summaries with Kimi (Moonshot's OpenAI-compatible API)."""
import os
import time

from openai import OpenAI, RateLimitError

from digest import paper as _paper

_client = None
_cache = {}          # (paper key, model) -> summary: a paper two subscribers get is summarized once


def _kimi():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("MOONSHOT_API_KEY"), base_url="https://api.moonshot.ai/v1")
    return _client


def summarize(paper, model):
    if not paper["abstract"]:
        return "No abstract available."
    key = (_paper.key(paper), model)
    if key in _cache:
        return _cache[key]
    for attempt in range(5):                # new Kimi accounts allow only 3 requests/min
        try:
            _cache[key] = _summarize_once(paper, model)
            return _cache[key]
        except RateLimitError:
            wait = 20 * (attempt + 1)
            print(f"  Kimi rate limit hit, waiting {wait}s...")
            time.sleep(wait)
    return "Summary unavailable (rate limited)."


def _summarize_once(paper, model):
    r = _kimi().chat.completions.create(
        model=model,
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
