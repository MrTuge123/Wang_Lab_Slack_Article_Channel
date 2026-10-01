"""How well each candidate fits the subscriber's interest: Kimi reads the titles and abstracts and
scores each paper 0-10, many papers per call (ranking.relevance_batch). The ranking uses it as one
part of the score (ranking.relevance_weight) and, if set, as a filter (ranking.min_relevance).
A paper Kimi couldn't score keeps relevance None and is ranked on the other parts alone."""
from openai import OpenAIError

from digest import llm
from digest import paper as _paper
from digest.summarizer import interest

SYSTEM = ("You screen newly published papers for a research group. From each paper's title and "
          "abstract, judge how closely it matches the readers' research interest. Be strict: sharing "
          "a few words with the interest is not enough; the paper's actual subject has to fit.")
SCALE = ("Score each paper from 0 to 10: 9-10 squarely on the interest (its topic and approach); "
         "6-8 clearly related, worth their time; 3-5 same broad field but a different focus; "
         "0-2 off topic.")
ABSTRACT_CHARS = 1500           # enough to judge the subject; keeps big batches cheap
_cache = {}                     # (paper key, model, interest) -> score (shared by subscribers)


def wanted(rank):
    """True if this subscriber's ranking uses relevance at all (else no Kimi calls are made)."""
    return rank.get("relevance_weight", 1.0) > 0 or rank.get("min_relevance", 0) > 0


def score_all(papers, sub):
    """Set p["relevance"] on every paper: 0-10, or None if Kimi couldn't score it."""
    model, readers = sub["model"], interest(sub)
    for p in papers:
        p["relevance"] = _cache.get((_paper.key(p), model, readers))
    if not readers:
        print("  No topic:/query:/interest: to judge relevance against; skipped.")
        return
    todo = [p for p in papers if p["relevance"] is None]
    size = max(1, int(sub["ranking"].get("relevance_batch", 25)))
    batches = [todo[i:i + size] for i in range(0, len(todo), size)]
    for b, batch in enumerate(batches, 1):
        if len(batches) > 1:
            print(f"  Batch {b} of {len(batches)} ({len(batch)} papers)")
        try:
            _score_batch(batch, readers, model)
        except (llm.RateLimited, OpenAIError, ValueError) as e:
            print(f"  Relevance scoring failed for {len(batch)} papers ({e}); ranking them without it.")
    missing = sum(p["relevance"] is None for p in papers)
    if missing:
        print(f"  {missing} of {len(papers)} papers have no relevance score.")


def _score_batch(batch, readers, model):
    items = [f"[{i}] {p['title']}\n{(p['abstract'] or '(no abstract)')[:ABSTRACT_CHARS]}"
             for i, p in enumerate(batch, 1)]
    reply = llm.ask_json(
        SYSTEM,
        f"Readers' research interest: {readers}\n\n{SCALE}\n\nPapers:\n\n" + "\n\n".join(items) + "\n\n"
        'Reply with JSON only, one integer score for every paper number, e.g. {"1": 7, "2": 2}.',
        model)
    scores = reply.get("scores") if isinstance(reply.get("scores"), dict) else reply
    for i, p in enumerate(batch, 1):
        try:
            v = float(scores.get(str(i)))
        except (TypeError, ValueError):
            continue                                # left unscored
        p["relevance"] = _cache[(_paper.key(p), model, readers)] = round(min(max(v, 0), 10))
