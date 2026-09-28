"""2-3 sentence plain-English summaries with Kimi, a 1-2 sentence overview of the whole digest,
and Simplified Chinese translations of both."""
from openai import OpenAIError

from digest import llm
from digest import paper as _paper

SYSTEM = ("You write summaries of new papers for a weekly literature digest read by researchers. "
          "Use only what the title and abstract say; never add facts, numbers or claims.")
ZH_SYSTEM = ("You translate short scientific summaries into Simplified Chinese for Chinese-speaking "
             "researchers. Be accurate and natural, and don't add or drop details.")
OVERVIEW_SYSTEM = ("You write the opening lines of a weekly literature digest read by researchers. "
                   "Be accurate and concise; use only what the titles and summaries say.")
STYLE = ("Start directly with the content (not 'This paper', 'The authors' or 'These papers'). "
         "No hype words (novel, groundbreaking, cutting-edge), no markdown.")
NO_ABSTRACT = "No abstract available."
RATE_LIMITED = "Summary unavailable (rate limited)."
_cache = {}          # (paper key, model, interest) -> summary (subscribers with the same interest share it)
_zh_cache = {}       # (paper key, model, interest) -> Chinese translation of that summary


def interest(sub):
    """The readers' research interest, for tailoring summaries: their topic or query, plus key_words."""
    if not sub:
        return ""
    text = sub.get("topic") or sub.get("query") or ""
    words = (sub.get("ranking") or {}).get("key_words") or []
    return text + (f" (keywords: {', '.join(words)})" if words else "")


def summarize(paper, model, sub=None):
    """2-3 sentences on the paper, tailored to the subscriber's interest when sub is given."""
    if not paper["abstract"]:
        return NO_ABSTRACT
    key = (_paper.key(paper), model, interest(sub))
    if key not in _cache:
        try:
            _cache[key] = _summarize_once(paper, model, interest(sub))
        except llm.RateLimited:
            return RATE_LIMITED
    return _cache[key]


def _usable(summary):
    return bool(summary) and summary not in (NO_ABSTRACT, RATE_LIMITED)


def translate_zh(text, model, title=None, abstract=None):
    """text in Simplified Chinese, or None if Kimi fails (the English then goes out alone).
    title and abstract (optional) give Kimi context for the terms; only the summary is translated."""
    try:
        return llm.ask(
            ZH_SYSTEM,
            (f"Title: {title}\n\n" if title else "")
            + (f"Abstract (context only, don't translate): {abstract[:2500]}\n\n" if abstract else "")
            + f"Summary: {text}\n\n"
            "Translate the summary into Simplified Chinese. Keep gene, protein and drug names, "
            "abbreviations (e.g. TNBC, PD-1) and numbers exactly as written. "
            "Reply with the translation only.",
            model)
    except (llm.RateLimited, OpenAIError) as e:
        print(f"  Chinese translation skipped ({e})")
        return None


def to_chinese(paper, model, sub=None):
    """The paper's English summary in Simplified Chinese, or None when there's nothing to translate
    or Kimi fails (the digest then goes out with the English summary only)."""
    if not _usable(paper.get("summary")):
        return None
    key = (_paper.key(paper), model, interest(sub))
    if key not in _zh_cache:
        zh = translate_zh(paper["summary"], model, title=paper["title"], abstract=paper.get("abstract"))
        if zh is None:
            return None
        _zh_cache[key] = zh
    return _zh_cache[key]


def overview(papers, model, sub=None):
    """1-2 sentences on what the digest's papers are about together, from their titles and summaries.
    None for a single paper (its own summary says it all) or if Kimi fails (the digest then goes
    out without it)."""
    if len(papers) < 2:
        return None
    items = [f"{i}. {p['title']}" + (f"\n   {p['summary']}" if _usable(p.get("summary")) else "")
             for i, p in enumerate(papers, 1)]
    readers = (f"Digest for: {sub.get('name')}\nReaders' research interest: {interest(sub)}\n\n"
               if sub else "")
    try:
        return llm.ask(
            OVERVIEW_SYSTEM,
            readers + "The papers in this week's digest:\n\n" + "\n\n".join(items) + "\n\n"
            "In 1-2 short sentences (at most 50 words in total), say what these papers are about as a "
            "group: the shared theme and, if there is one, the most notable finding for these readers. "
            "Give the big picture; don't list or describe the papers one by one. " + STYLE +
            " Reply with the sentences only.",
            model)
    except (llm.RateLimited, OpenAIError) as e:
        print(f"  Overview skipped ({e})")
        return None


def _summarize_once(paper, model, readers_interest=""):
    return llm.ask(
        SYSTEM,
        (f"Readers' research interest: {readers_interest}\n\n" if readers_interest else "")
        + f"Title: {paper['title']}\n\nAbstract: {paper['abstract']}\n\n"
        "Write 2-3 sentences (at most 70 words), plain text:\n"
        "1. What problem they tackled and how (method, data or model system).\n"
        "2. The main result, with the key numbers from the abstract if it gives them.\n"
        "3. Only if the abstract clearly supports it: why it matters for the readers' interest.\n"
        + STYLE + " Spell out an abbreviation the first time unless it is standard in the field. "
        "If the abstract reports no results, say what they set out to do instead. "
        "Reply with the summary only.",
        model)
