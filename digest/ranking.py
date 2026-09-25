"""Score, filter and sort papers by author / journal impact and keywords.
`rank` is the subscriber's ranking: settings (config.yaml defaults + the subscriber's overrides)."""
import re


def _norm(s):
    return s.strip().lower()


def _words(s):
    """'Multi-Omics Integration' -> ' multi omics integration ' (padded for whole-word matching)"""
    return " " + " ".join(re.findall(r"\w+", s.lower())) + " "


def keyword_hits(p, rank):
    """The subscriber's key_words found in the paper's author keywords, each counted once.
    Whole words only: 'diabetes' matches 'Type 2 Diabetes' but not 'diabetic'."""
    kws = [_words(k) for k in p["keywords"]]
    return [t for t in rank.get("key_words") or [] if any(_words(t) in k for k in kws)]


def is_preferred_author(p, rank):
    prefs = {_norm(a) for a in rank.get("preferred_authors") or []}
    ids = {_norm(i) for i in p.get("author_ids", [])}
    names = {_norm(n) for n in p.get("author_names", []) + p["authors"]}
    return bool(prefs & (ids | names))


def is_preferred_journal(p, rank):
    prefs = {_norm(j) for j in rank.get("preferred_journals") or []}
    names = {_norm(p["journal"])}
    if p.get("source"):
        names.add(_norm(p["source"]["name"]))
    return bool(prefs & names)


def author_h(p):
    return p["top_author"]["h"] if p.get("top_author") else 0


def journal_citedness(p):
    return p["source"]["citedness"] if p.get("source") else 0


def score(p, rank):
    wa, wj = rank.get("author_weight", 0.6), rank.get("journal_weight", 0.4)
    if p.get("oa_matched"):
        a = min(author_h(p) / rank.get("author_h_cap", 60), 1)
        j = min(journal_citedness(p) / rank.get("journal_citedness_cap", 10), 1)
    else:
        a = j = rank.get("unmatched_score", 0.3)
    if p.get("preprint"):                      # no journal yet: neutral journal score
        j = rank.get("preprint_journal_score", rank.get("unmatched_score", 0.3))
    if is_preferred_author(p, rank):
        a = 1.0
    if is_preferred_journal(p, rank):
        j = 1.0
    credit = rank.get("keyword_credit", 0.1) * len(p["keyword_hits"])
    return round((wa * a + wj * j) / (wa + wj) + credit, 3)


def passes_filters(p, rank):
    if is_preferred_author(p, rank) or is_preferred_journal(p, rank):
        return True
    if p["score"] < rank.get("min_score", 0):
        return False
    if p.get("preprint") and not rank.get("keep_preprints", True):
        return False
    if not p.get("oa_matched"):
        return rank.get("keep_unmatched", True)
    return (author_h(p) >= rank.get("min_author_h_index", 0)
            and (p.get("preprint")                # no journal to hold to min_journal_citedness
                 or journal_citedness(p) >= rank.get("min_journal_citedness", 0)))


def rank_papers(papers, rank):
    """Add keyword_hits, score and passed to each paper; return them best first."""
    for p in papers:
        p["keyword_hits"] = keyword_hits(p, rank)
        p["score"] = score(p, rank)
        p["passed"] = passes_filters(p, rank)
    return sorted(papers, key=lambda p: p["score"], reverse=True)


SOURCE_ABBR = {"PubMed": "PM", "Europe PMC": "EP", "OpenAlex": "OA", "Semantic Scholar": "S2", "arXiv": "AX"}


def print_ranking(papers):
    print(f"\n{'score':>5}  {'h':>4}  {'role':<22}  {'jrnl':>5}  {'kw':>2}  pass  {'found in':<14}  title")
    for p in papers:
        flag = "yes" if p["passed"] else "no"
        tag = ("" if p.get("oa_matched") else " [not in OpenAlex]") + (" [preprint]" if p.get("preprint") else "")
        role = (p.get("top_author") or {}).get("role", "")
        found = ",".join(SOURCE_ABBR.get(s, s) for s in p["sources"])
        jrnl = "-" if p.get("preprint") else journal_citedness(p)
        print(f"{p['score']:>5.2f}  {author_h(p):>4}  {role:<22}  {jrnl:>5}  "
              f"{len(p['keyword_hits']):>2}  {flag:<4}  {found:<14}  {p['title'][:60]}{tag}")
    print("(found in: PM PubMed, EP Europe PMC, OA OpenAlex, S2 Semantic Scholar, AX arXiv)\n")
