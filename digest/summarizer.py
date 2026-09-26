"""2-3 sentence plain-English summaries with Kimi, and their Simplified Chinese translation."""
from openai import OpenAIError

from digest import llm
from digest import paper as _paper

SYSTEM = ("You summarize scientific papers for a research lab's Slack channel. "
          "Be accurate, concise, and don't invent details.")
ZH_SYSTEM = ("You translate short scientific summaries into Simplified Chinese for Chinese-speaking "
             "researchers. Be accurate and natural, and don't add or drop details.")
NO_ABSTRACT = "No abstract available."
RATE_LIMITED = "Summary unavailable (rate limited)."
_cache = {}          # (paper key, model) -> summary: a paper two subscribers get is summarized once
_zh_cache = {}       # (paper key, model) -> Chinese translation of that summary


def summarize(paper, model):
    if not paper["abstract"]:
        return NO_ABSTRACT
    key = (_paper.key(paper), model)
    if key not in _cache:
        try:
            _cache[key] = _summarize_once(paper, model)
        except llm.RateLimited:
            return RATE_LIMITED
    return _cache[key]


def to_chinese(paper, model):
    """The paper's English summary in Simplified Chinese, or None when there's nothing to translate
    or Kimi fails (the digest then goes out with the English summary only)."""
    english = paper.get("summary")
    if not english or english in (NO_ABSTRACT, RATE_LIMITED):
        return None
    key = (_paper.key(paper), model)
    if key not in _zh_cache:
        try:
            _zh_cache[key] = llm.ask(
                ZH_SYSTEM,
                f"Title: {paper['title']}\n\nSummary: {english}\n\n"
                "Translate the summary into Simplified Chinese. Keep gene, protein and drug names, "
                "abbreviations (e.g. TNBC, PD-1) and numbers exactly as written. "
                "Reply with the translation only.",
                model)
        except (llm.RateLimited, OpenAIError) as e:
            print(f"  Chinese summary skipped ({e})")
            return None
    return _zh_cache[key]


def _summarize_once(paper, model):
    return llm.ask(SYSTEM, f"Title: {paper['title']}\n\nAbstract: {paper['abstract']}\n\n"
                           "Write a 2-3 sentence plain-English summary: what they did and the key finding.",
                   model)
