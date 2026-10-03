"""How well each candidate fits the subscriber's interest: Kimi reads the titles and abstracts and
scores each paper 0-10, many papers per call (ranking.relevance_batch). The ranking uses it as one
part of the score (ranking.relevance_weight) and, if set, as a filter (ranking.min_relevance).
A paper Kimi couldn't score keeps relevance None and is ranked on the other parts alone.

Kimi answers without reasoning first (ranking.relevance_thinking: false): ~25x faster, far fewer
tokens and steadier scores. Scores saved in history/ by earlier runs are reused while the interest,
model and reasoning setting are unchanged, so a paper that stays a candidate for weeks is scored once."""
import hashlib

from openai import OpenAIError

from digest import llm
from digest import paper as _paper
from digest.history import load_history
from digest.summarizer import interest

SYSTEM = ("You screen newly published papers for a research group. From each paper's title and "
          "abstract, judge how closely it matches the readers' research interest. Be strict: sharing "
          "a few words with the interest is not enough; the paper's actual subject has to fit.")
SCALE = ("Score each paper from 0 to 10: 9-10 squarely on the interest (its topic and approach); "
         "6-8 clearly related, worth their time; 3-5 same broad field but a different focus; "
         "0-2 off topic.")
ABSTRACT_CHARS = 1500           # enough to judge the subject; keeps big batches cheap
_cache = {}                     # (paper key, stamp) -> score (shared by subscribers judged the same way)


def wanted(rank):
    """True if this subscriber's ranking uses relevance at all (else no Kimi calls are made)."""
    return rank.get("relevance_weight", 1.0) > 0 or rank.get("min_relevance", 0) > 0


def stamp(readers, model, thinking):
    """Short fingerprint of how a score was judged (interest text, model, reasoning on/off),
    saved next to it in history/ as relevance_for."""
    return hashlib.sha1(f"{model}|{thinking}|{readers}".encode()).hexdigest()[:12]


def _from_history(papers, sid, tag):
    """Fill in scores earlier runs saved in history/<sid>.jsonl that were judged the same way.
    Returns how many papers got one."""
    saved = {i: r["relevance"] for r in load_history(sid)
             if r.get("relevance") is not None and r.get("relevance_for") == tag for i in r["ids"]}
    n = 0
    for p in papers:
        if p["relevance"] is None:
            p["relevance"] = next((saved[i] for i in _paper.ids(p) if i in saved), None)
            n += p["relevance"] is not None
    return n


def score_all(papers, sub):
    """Set p["relevance"] on every paper: 0-10, or None if Kimi couldn't score it.
    Scored papers also get p["relevance_for"], the stamp history/ saves with the score."""
    model, readers = sub["model"], interest(sub)
    thinking = bool(sub["ranking"].get("relevance_thinking", False))
    tag = stamp(readers, model, thinking)
    for p in papers:
        p["relevance"] = _cache.get((_paper.key(p), tag))
    if not readers:
        print("  No topic:/query:/interest: to judge relevance against; skipped.")
        return
    reused = _from_history(papers, sub["id"], tag)
    if reused:
        print(f"  Reused {reused} scores from earlier runs (same interest and model).")
    todo = [p for p in papers if p["relevance"] is None]
    size = max(1, int(sub["ranking"].get("relevance_batch", 25)))
    batches = [todo[i:i + size] for i in range(0, len(todo), size)]
    for b, batch in enumerate(batches, 1):
        if len(batches) > 1:
            print(f"  Batch {b} of {len(batches)} ({len(batch)} papers)")
        try:
            _score_batch(batch, readers, model, thinking, tag)
        except (llm.RateLimited, OpenAIError, ValueError) as e:
            print(f"  Relevance scoring failed for {len(batch)} papers ({e}); ranking them without it.")
    for p in papers:
        if p["relevance"] is not None:
            p["relevance_for"] = tag
    missing = sum(p["relevance"] is None for p in papers)
    if missing:
        print(f"  {missing} of {len(papers)} papers have no relevance score.")


def _score_batch(batch, readers, model, thinking, tag):
    items = [f"[{i}] {p['title']}\n{(p['abstract'] or '(no abstract)')[:ABSTRACT_CHARS]}"
             for i, p in enumerate(batch, 1)]
    reply = llm.ask_json(
        SYSTEM,
        f"Readers' research interest: {readers}\n\n{SCALE}\n\nPapers:\n\n" + "\n\n".join(items) + "\n\n"
        'Reply with JSON only, one integer score for every paper number, e.g. {"1": 7, "2": 2}.',
        model, thinking=thinking)
    scores = reply.get("scores") if isinstance(reply.get("scores"), dict) else reply
    for i, p in enumerate(batch, 1):
        try:
            v = float(scores.get(str(i)))
        except (TypeError, ValueError):
            continue                                # left unscored
        p["relevance"] = _cache[(_paper.key(p), tag)] = round(min(max(v, 0), 10))
