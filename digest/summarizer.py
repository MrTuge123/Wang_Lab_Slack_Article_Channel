"""2-3 sentence plain-English summaries with Kimi."""
from digest import llm
from digest import paper as _paper

SYSTEM = ("You summarize scientific papers for a research lab's Slack channel. "
          "Be accurate, concise, and don't invent details.")
_cache = {}          # (paper key, model) -> summary: a paper two subscribers get is summarized once


def summarize(paper, model):
    if not paper["abstract"]:
        return "No abstract available."
    key = (_paper.key(paper), model)
    if key not in _cache:
        try:
            _cache[key] = _summarize_once(paper, model)
        except llm.RateLimited:
            return "Summary unavailable (rate limited)."
    return _cache[key]


def _summarize_once(paper, model):
    return llm.ask(SYSTEM, f"Title: {paper['title']}\n\nAbstract: {paper['abstract']}\n\n"
                           "Write a 2-3 sentence plain-English summary: what they did and the key finding.",
                   model)
