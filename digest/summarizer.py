"""2-3 sentence plain-English summaries with Kimi, an overview of the whole digest, and Simplified
Chinese translations of both.

Batched to save Kimi calls (new accounts allow only ~3 a minute):
- summarize_all(): one call writes every paper's summary and the overview.
- translate_all(): one call translates them all (only for chats with chinese_summary: true).
If a batched reply can't be used, the papers it missed fall back to one call each."""
from openai import OpenAIError

from digest import llm
from digest import paper as _paper
from digest.notify.format import period

SYSTEM = ("You are an expert in the given field writing summaries of new papers for a literature digest "
          "read by researchers. Use only what the titles and abstracts say; never add facts, numbers or claims.")
ZH_SYSTEM = ("You translate short scientific summaries into Simplified Chinese for Chinese-speaking "
             "researchers. Be accurate and natural, and don't add or drop details.")
OVERVIEW_SYSTEM = ("You are an expert in the given field writing the opening paragraph of a literature "
                   "digest read by researchers: a picture of the recent literature in their area. "
                   "Be accurate and concise; use only what the titles, abstracts and summaries say.")
STYLE = ("Start directly with the content (not 'This paper', 'The authors' or 'These papers'). "
         "No hype words (novel, groundbreaking, cutting-edge), no markdown.")
SUMMARY_RULES = (
    "2-3 sentences (at most 70 words), plain text:\n"
    "1. What problem they tackled and how (method, data or model system).\n"
    "2. The main result, with the key numbers from the abstract if it gives them.\n"
    "3. Only if the abstract clearly supports it: why it matters for the readers' interest.\n"
    + STYLE + " Spell out an abbreviation the first time unless it is standard in the field. "
    "If the abstract reports no results, say what they set out to do instead.")
OVERVIEW_RULES = (
    "one paragraph of 4-6 sentences (at most 160 words), plain text, about the research landscape, "
    "not a list of papers:\n"
    "1. The general focus: what the relevant papers found in this period are mostly about, as a whole. "
    "Name the 2-3 main research directions they cluster into (a method family, disease or biological "
    "system, data type) with rough counts where clear, e.g. 'about ten papers apply graph attention "
    "networks to spatial transcriptomics'. Base this on ALL the relevant papers listed, not only the "
    "selected ones.\n"
    "2. A notable trend within it (a method or question that keeps coming up, or a shift in focus), "
    "only if the list clearly shows one.\n"
    "3. Why the selected papers were picked and which of those directions they represent, citing them "
    "by number, e.g. (#2, #4). They ranked highest on fit to the readers' interest, author and journal "
    "impact, and keyword matches. Don't describe their methods or results: the summary under each "
    "paper does that.\n"
    "Don't give numbers from individual papers. If the papers don't share a clear focus, say they are "
    "spread out and name the areas; never invent a theme. Avoid generic framings such as 'advances in', "
    "'highlight the potential of', 'diverse applications'. " + STYLE)
OVERVIEW_POOL_MAX = 60      # most other relevant titles shown to Kimi for the overview
ZH_RULES = ("Keep gene, protein and drug names, abbreviations (e.g. TNBC, PD-1) and numbers exactly "
            "as written.")
NO_ABSTRACT = "No abstract available."
RATE_LIMITED = "Summary unavailable (rate limited)."
_cache = {}          # (paper key, model, interest) -> summary (subscribers with the same interest share it)
_zh_cache = {}       # (paper key, model, interest) -> Chinese translation of that summary


def interest(sub):
    """The readers' research interest, for judging relevance and tailoring summaries: their
    interest: (plain English), else topic: or query:, plus key_words."""
    if not sub:
        return ""
    text = sub.get("interest") or sub.get("topic") or sub.get("query") or ""
    words = (sub.get("ranking") or {}).get("key_words") or []
    return text + (f" (keywords: {', '.join(words)})" if words else "")


def _readers(sub):
    if not sub:
        return ""
    when = f", papers from {period(sub)}" if sub.get("days_back") else ""
    return f"Digest for: {sub.get('name')}{when}\nReaders' research interest: {interest(sub)}\n\n"


def _key(paper, model, sub):
    return (_paper.key(paper), model, interest(sub))


def _usable(summary):
    return bool(summary) and summary not in (NO_ABSTRACT, RATE_LIMITED)


def _text(v):
    """v stripped if it's a non-empty string, else None (for values out of Kimi's JSON)."""
    return v.strip() if isinstance(v, str) and v.strip() else None


def _landscape(papers, pool, sub):
    """For the overview: how many candidates there were and the titles of the other relevant ones.
    Relevant = Kimi relevance at or above overview_min_relevance (all candidates if unscored)."""
    if not pool:
        return ""
    chosen = {id(p) for p in papers}
    rest = [p for p in pool if id(p) not in chosen]
    cutoff = (sub or {}).get("overview_min_relevance", 5)
    scored = any(p.get("relevance") is not None for p in pool)
    if scored:
        rest = [p for p in rest if p.get("relevance") is not None and p["relevance"] >= cutoff]
        which = f"judged relevant to the readers (relevance {cutoff}/10 or more)"
    else:
        which = "found"
    shown = rest[:OVERVIEW_POOL_MAX]
    head = (f"\n\nThe selected papers above are the top {len(papers)} of {len(pool)} candidates found "
            f"in {period(sub) if sub and sub.get('days_back') else 'this period'}. "
            f"{len(rest) + len(papers)} candidates were {which}; the other "
            f"{len(rest)} are listed here by title (best ranked first"
            + (f", first {len(shown)} shown" if len(shown) < len(rest) else "") + "):\n")
    return head + "\n".join(f"- {p['title']}" for p in shown)


# ---------- English: batched ----------

def summarize_all(papers, model, sub=None, pool=None):
    """Set p["summary"] on every paper and return the digest's overview: None for a single paper
    (its own summary says it all) or if Kimi fails (the digest then goes out without it).
    pool: every ranked candidate (best first), so the overview can describe the wider literature.
    Normally one Kimi call; papers it misses are summarized one call each."""
    want_overview = len(papers) >= 2
    todo = []
    for p in papers:
        if not p["abstract"]:
            p["summary"] = NO_ABSTRACT
        elif _key(p, model, sub) in _cache:
            p["summary"] = _cache[_key(p, model, sub)]
        else:
            p["summary"] = None
            todo.append(p)
    text = None
    if todo:
        try:
            text = _summarize_batch(papers, todo, model, sub, want_overview, pool)
        except (llm.RateLimited, OpenAIError, ValueError) as e:
            print(f"  Batched summaries failed ({e}); summarizing one paper at a time.")
    for p in todo:
        if p["summary"] is None:
            p["summary"] = summarize(p, model, sub)
    if want_overview and not text:
        text = overview(papers, model, sub, pool)
    return text


def _summarize_batch(papers, todo, model, sub, want_overview, pool=None):
    """One call for the summaries of `todo` (and the overview of all `papers`). Returns the overview."""
    items = []
    for i, p in enumerate(papers, 1):
        if p in todo:
            items.append(f"[{i}] Title: {p['title']}\nAbstract: {p['abstract']}")
        elif _usable(p["summary"]):
            items.append(f"[{i}] Title: {p['title']}\nSummary (already written): {p['summary']}")
        else:
            items.append(f"[{i}] Title: {p['title']}\n(no abstract)")
    nums = [str(papers.index(p) + 1) for p in todo]
    task = (f"For each of papers {', '.join(nums)}, write a summary: {SUMMARY_RULES}\n\n")
    shape = '{"summaries": {"' + nums[0] + '": "..."}}'
    if want_overview:
        task += f"Also write the overview that opens the digest: {OVERVIEW_RULES}\n\n"
        shape = shape[:-1] + ', "overview": "..."}'
    reply = llm.ask_json(
        SYSTEM,
        _readers(sub) + "Selected papers:\n\n" + "\n\n".join(items)
        + (_landscape(papers, pool, sub) if want_overview else "") + "\n\n" + task
        + "Reply with JSON only: " + shape + ", with one summary per paper number listed above.",
        model)
    summaries = reply.get("summaries") if isinstance(reply.get("summaries"), dict) else {}
    for n, p in zip(nums, todo):
        s = _text(summaries.get(n))
        if s:
            p["summary"] = _cache[_key(p, model, sub)] = s
    missed = sum(p["summary"] is None for p in todo)
    if missed:
        print(f"  Kimi's reply left out {missed} summar{'y' if missed == 1 else 'ies'}; writing them one by one.")
    return _text(reply.get("overview")) if want_overview else None


# ---------- English: one at a time (fallbacks) ----------

def summarize(paper, model, sub=None):
    """2-3 sentences on one paper, tailored to the subscriber's interest when sub is given."""
    if not paper["abstract"]:
        return NO_ABSTRACT
    key = _key(paper, model, sub)
    if key not in _cache:
        try:
            _cache[key] = llm.ask(
                SYSTEM,
                (f"Readers' research interest: {interest(sub)}\n\n" if sub else "")
                + f"Title: {paper['title']}\n\nAbstract: {paper['abstract']}\n\n"
                f"Write {SUMMARY_RULES} Reply with the summary only.",
                model)
        except llm.RateLimited:
            return RATE_LIMITED
    return _cache[key]


def overview(papers, model, sub=None, pool=None):
    """The digest's overview from the papers' titles and summaries (and the other relevant
    candidates' titles in pool); None for a single paper or if Kimi fails."""
    if len(papers) < 2:
        return None
    items = [f"{i}. {p['title']}" + (f"\n   {p['summary']}" if _usable(p.get("summary")) else "")
             for i, p in enumerate(papers, 1)]
    try:
        return llm.ask(
            OVERVIEW_SYSTEM,
            _readers(sub) + "Selected papers:\n\n" + "\n\n".join(items) + _landscape(papers, pool, sub)
            + f"\n\nWrite {OVERVIEW_RULES} Reply with the paragraph only.",
            model)
    except (llm.RateLimited, OpenAIError) as e:
        print(f"  Overview skipped ({e})")
        return None


# ---------- Chinese ----------

def translate_all(papers, overview_text, model, sub=None):
    """Set p["summary_zh"] on every paper and return the overview in Chinese. One Kimi call;
    whatever it misses is translated one call each. None wherever there's nothing to translate
    or Kimi fails (that part then goes out in English only)."""
    todo = {}
    for i, p in enumerate(papers, 1):
        p["summary_zh"] = None
        if not _usable(p.get("summary")):
            continue
        key = _key(p, model, sub)
        if key in _zh_cache:
            p["summary_zh"] = _zh_cache[key]
        else:
            todo[str(i)] = p
    if not todo and not overview_text:
        return None
    overview_zh = None
    items = [f"[{n}] (title, for context only: {p['title']})\n{p['summary']}" for n, p in todo.items()]
    if overview_text:
        items.append(f"[overview]\n{overview_text}")
    try:
        reply = llm.ask_json(
            ZH_SYSTEM,
            "Translate each numbered text below into Simplified Chinese (not the titles). " + ZH_RULES
            + "\n\n" + "\n\n".join(items) + "\n\n"
            'Reply with JSON only, the translation under each label, e.g. {"1": "...", "overview": "..."}.',
            model)
        for n, p in todo.items():
            zh = _text(reply.get(n))
            if zh:
                p["summary_zh"] = _zh_cache[_key(p, model, sub)] = zh
        overview_zh = _text(reply.get("overview")) if overview_text else None
    except (llm.RateLimited, OpenAIError, ValueError) as e:
        print(f"  Batched Chinese translation failed ({e}); translating one at a time.")
    for p in todo.values():
        if not p["summary_zh"]:
            p["summary_zh"] = to_chinese(p, model, sub)
    if overview_text and not overview_zh:
        overview_zh = translate_zh(overview_text, model)
    return overview_zh


def translate_zh(text, model, title=None, abstract=None):
    """text in Simplified Chinese, or None if Kimi fails (the English then goes out alone).
    title and abstract (optional) give Kimi context for the terms; only the summary is translated."""
    try:
        return llm.ask(
            ZH_SYSTEM,
            (f"Title: {title}\n\n" if title else "")
            + (f"Abstract (context only, don't translate): {abstract[:2500]}\n\n" if abstract else "")
            + f"Summary: {text}\n\n"
            f"Translate the summary into Simplified Chinese. {ZH_RULES} Reply with the translation only.",
            model)
    except (llm.RateLimited, OpenAIError) as e:
        print(f"  Chinese translation skipped ({e})")
        return None


def to_chinese(paper, model, sub=None):
    """One paper's English summary in Simplified Chinese, or None when there's nothing to translate
    or Kimi fails."""
    if not _usable(paper.get("summary")):
        return None
    key = _key(paper, model, sub)
    if key not in _zh_cache:
        zh = translate_zh(paper["summary"], model, title=paper["title"], abstract=paper.get("abstract"))
        if zh is None:
            return None
        _zh_cache[key] = zh
    return _zh_cache[key]
