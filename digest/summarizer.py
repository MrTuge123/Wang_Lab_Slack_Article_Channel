"""2-3 sentence plain-English summaries with Kimi, a 1-2 sentence overview of the whole digest,
and Simplified Chinese translations of both."""
from openai import OpenAIError

from digest import llm
from digest import paper as _paper

SYSTEM = ("You summarize scientific papers for a research lab's Slack channel. "
          "Be accurate, concise, and don't invent details.")
ZH_SYSTEM = ("You translate short scientific summaries into Simplified Chinese for Chinese-speaking "
             "researchers. Be accurate and natural, and don't add or drop details.")
OVERVIEW_SYSTEM = ("You write the opening lines of a research lab's paper digest. "
                   "Be accurate and concise, and don't invent details.")
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


def _usable(summary):
    return bool(summary) and summary not in (NO_ABSTRACT, RATE_LIMITED)


def translate_zh(text, model, title=None):
    """text in Simplified Chinese, or None if Kimi fails (the English then goes out alone).
    title (optional) gives Kimi context for the terms."""
    try:
        return llm.ask(
            ZH_SYSTEM,
            (f"Title: {title}\n\n" if title else "") + f"Summary: {text}\n\n"
            "Translate the summary into Simplified Chinese. Keep gene, protein and drug names, "
            "abbreviations (e.g. TNBC, PD-1) and numbers exactly as written. "
            "Reply with the translation only.",
            model)
    except (llm.RateLimited, OpenAIError) as e:
        print(f"  Chinese translation skipped ({e})")
        return None


def to_chinese(paper, model):
    """The paper's English summary in Simplified Chinese, or None when there's nothing to translate
    or Kimi fails (the digest then goes out with the English summary only)."""
    if not _usable(paper.get("summary")):
        return None
    key = (_paper.key(paper), model)
    if key not in _zh_cache:
        zh = translate_zh(paper["summary"], model, title=paper["title"])
        if zh is None:
            return None
        _zh_cache[key] = zh
    return _zh_cache[key]


def overview(papers, model):
    """1-2 sentences on what the digest's papers are about together, from their titles and summaries.
    None for a single paper (its own summary says it all) or if Kimi fails (the digest then goes
    out without it)."""
    if len(papers) < 2:
        return None
    items = [f"{i}. {p['title']}" + (f"\n   {p['summary']}" if _usable(p.get("summary")) else "")
             for i, p in enumerate(papers, 1)]
    try:
        return llm.ask(
            OVERVIEW_SYSTEM,
            "The papers in today's digest:\n\n" + "\n\n".join(items) + "\n\n"
            "In 1-2 short sentences (at most 50 words in total), say what these papers are about as a "
            "group: the shared theme and, if there is one, the most notable finding. Give the big "
            "picture; don't list or describe the papers one by one. Reply with the sentences only.",
            model)
    except (llm.RateLimited, OpenAIError) as e:
        print(f"  Overview skipped ({e})")
        return None


def _summarize_once(paper, model):
    return llm.ask(SYSTEM, f"Title: {paper['title']}\n\nAbstract: {paper['abstract']}\n\n"
                           "Write a 2-3 sentence plain-English summary: what they did and the key finding.",
                   model)
