"""One search query, translated into every source's syntax.

Write it once in a simple boolean form:
    "graph neural network" AND ("knowledge graph" OR KG) NOT review
- terms are words or "quoted phrases"
- combine with AND, OR, NOT (upper case) and parentheses; terms side by side are ANDed
- a PubMed field tag like "x"[tiab] or cancer[mesh] is kept for PubMed and dropped elsewhere

Or describe the topic in plain English (topic: in the subscriber file) and Kimi writes the
boolean query on each run (see from_topic).

Preview what each source gets:
    python -m digest.query '"graph neural network" AND ("knowledge graph" OR KG)'
    python -m digest.query --topic "graph neural networks for biomedical knowledge graphs"
"""
import re
import sys
from dataclasses import dataclass


class QueryError(ValueError):
    pass


@dataclass(frozen=True)
class Term:
    text: str
    phrase: bool
    tag: str = ""              # PubMed field tag with brackets, e.g. "[tiab]"


@dataclass(frozen=True)
class And:
    items: tuple


@dataclass(frozen=True)
class Or:
    items: tuple


@dataclass(frozen=True)
class Not:
    item: object


# ---------- Parse ----------
_TOKEN = re.compile(r'(?P<lp>\()|(?P<rp>\))|"(?P<phrase>[^"]*)"(?P<ptag>\[[^\]]*\])?'
                    r'|(?P<word>[^\s()"\[]+)(?P<wtag>\[[^\]]*\])?')
_OPS = {"AND", "OR", "NOT"}


def _tokenize(text):
    toks, pos = [], 0
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos == len(text):
            return toks
        m = _TOKEN.match(text, pos)
        if not m:
            raise QueryError(f"can't read the query from here: {text[pos:pos + 20]!r} (unclosed quote?)")
        pos = m.end()
        if m["lp"]:
            toks.append(("(",))
        elif m["rp"]:
            toks.append((")",))
        elif m["phrase"] is not None:
            if m["phrase"].strip():
                toks.append(("term", Term(" ".join(m["phrase"].split()), True, m["ptag"] or "")))
        elif m["word"] in _OPS and not m["wtag"]:
            toks.append(("op", m["word"]))
        else:
            toks.append(("term", Term(m["word"], False, m["wtag"] or "")))


def _flat(cls, items):
    out = []
    for i in items:
        out += i.items if isinstance(i, cls) else [i]
    return out[0] if len(out) == 1 else cls(tuple(out))


def parse(text):
    """Query text -> tree of Term / And / Or / Not. Raises QueryError on bad syntax."""
    toks = _tokenize(text or "")
    if not toks:
        raise QueryError("the query is empty")
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def take():
        nonlocal pos
        pos += 1
        return toks[pos - 1] if pos <= len(toks) else None

    def p_or():
        parts = [p_and()]
        while peek() == ("op", "OR"):
            take()
            parts.append(p_and())
        if len(parts) > 1 and any(n > 1 for _, n in parts):
            # Sources disagree here (PubMed reads left to right, the others bind AND first)
            raise QueryError("AND/NOT and OR are mixed without parentheses: write (A OR B) AND C "
                             'or A OR (B AND C); multi-word terms next to OR need "quotes"')
        return _flat(Or, [node for node, _ in parts])

    def p_and():
        """(node, number of ANDed parts) - the count lets p_or spot unparenthesized mixing."""
        items = [p_unary()]
        while peek() not in (None, (")",), ("op", "OR")):
            t = take() if peek()[0] == "op" else None       # AND / NOT, or nothing (implicit AND)
            items.append(Not(p_unary()) if t == ("op", "NOT") else p_unary())
        return _flat(And, items), len(items)

    def p_unary():
        if peek() == ("op", "NOT"):
            take()
            return Not(p_unary())
        return p_primary()

    def p_primary():
        t = take()
        if t is None:
            raise QueryError("the query ends where a term was expected")
        if t == ("(",):
            node = p_or()
            if take() != (")",):
                raise QueryError("a ( is never closed")
            return node
        if t[0] == "term":
            return t[1]
        raise QueryError(f"expected a term but found {t[-1]!r}")

    node = p_or()
    if pos < len(toks):
        raise QueryError(f"unexpected {toks[pos][-1]!r} (extra ) ?)")
    _check_nots(node)
    return node


def _check_nots(node):
    """Every source needs something to exclude from: 'A NOT B' works, 'NOT B' or 'A OR NOT B' don't."""
    if isinstance(node, Not):
        raise QueryError("NOT needs something before it, e.g. A NOT B")
    if isinstance(node, Or):
        for i in node.items:
            _check_nots(i)
    if isinstance(node, And):
        if all(isinstance(i, Not) for i in node.items):
            raise QueryError("NOT needs something before it, e.g. A NOT B")
        for i in node.items:
            _check_nots(i.item if isinstance(i, Not) else i)


# ---------- Render ----------
def _render(node, term, andnot):
    """Generic boolean renderer. term(Term) -> str; andnot(positive_str, [negative_str]) -> str."""
    def wrap(n):
        s = _render(n, term, andnot)
        return f"({s})" if isinstance(n, (And, Or)) else s

    if isinstance(node, Term):
        return term(node)
    if isinstance(node, Or):
        return " OR ".join(wrap(i) for i in node.items)
    pos = " AND ".join(wrap(i) for i in node.items if not isinstance(i, Not))
    neg = [wrap(i.item) for i in node.items if isinstance(i, Not)]
    return andnot(pos, neg) if neg else pos


def _plain_term(t, keep_tag=False):
    s = f'"{t.text}"' if t.phrase else t.text
    return s + (t.tag if keep_tag else "")


def _not_style(pos, neg):
    return pos + "".join(f" NOT {n}" for n in neg)


def to_pubmed(node):
    return _render(node, lambda t: _plain_term(t, keep_tag=True), _not_style)


def to_plain(node):
    """Europe PMC and OpenAlex: same boolean syntax, no PubMed tags."""
    return _render(node, _plain_term, _not_style)


def to_arxiv(node, field="abs"):
    """arXiv needs a field on every term (abs = abstract) and spells NOT as ANDNOT."""
    return _render(node, lambda t: f"{field}:{_plain_term(t)}",
                   lambda pos, neg: f"{pos} ANDNOT " + (neg[0] if len(neg) == 1 else f"({' OR '.join(neg)})"))


def to_keywords(node):
    """Semantic Scholar's relevance search takes plain words: the ANDed terms, the first
    alternative of each OR group, and nothing that's NOT-ed."""
    def words(n):
        if isinstance(n, Term):
            return [n.text]
        if isinstance(n, Or):
            return words(n.items[0])
        if isinstance(n, And):
            return [w for i in n.items if not isinstance(i, Not) for w in words(i)]
        return []
    return " ".join(words(node))


RENDERERS = {                   # source key (as under sources: in config) -> renderer
    "pubmed": to_pubmed,
    "europepmc": to_plain,
    "openalex": to_plain,
    "semantic_scholar": to_keywords,
    "arxiv": to_arxiv,
}


def render(node, source):
    return RENDERERS[source](node)


# ---------- Topic mode: Kimi writes the boolean query ----------
TOPIC_PROMPT = """You write literature-search queries. Given a research topic, reply with ONE boolean query:
- terms are single words or "quoted phrases"
- combine them with AND, OR, NOT (upper case) and parentheses
- usually 2-3 concepts joined by AND; each concept is an OR group of its common synonyms,
  spelling variants and abbreviations (e.g. ("graph neural network" OR GNN))
- no field tags, no wildcards, no explanation, no code block
Reply with the query only."""
_topic_cache = {}


def _candidates(reply):
    """Lines of Kimi's reply that could be the query (code fences and a 'Query:' label removed)."""
    for line in (reply or "").splitlines():
        line = re.sub(r"^(query\s*:)", "", line.strip().strip("`").strip(), flags=re.I).strip()
        if line:
            yield line


def from_topic(topic, model):
    """Kimi turns a plain-English topic into a boolean query (checked by parse()).
    Returns (query text, parsed tree). Asked once per topic per run."""
    from digest import llm                       # (here so query previews don't need the OpenAI package)
    key = (topic, model)
    if key not in _topic_cache:
        user = f"Topic: {topic}"
        for attempt in range(2):                # one retry, telling Kimi what was wrong
            reply = llm.ask(TOPIC_PROMPT, user, model)
            error = "empty reply"
            for text in _candidates(reply):
                try:
                    _topic_cache[key] = (text, parse(text))
                    break
                except QueryError as e:
                    error = f"`{text}` is invalid: {e}"
            if key in _topic_cache:
                break
            user = f"Topic: {topic}\n\nYour previous reply was not usable ({error}). Try again."
        else:
            raise RuntimeError(f"Kimi didn't produce a valid query for topic {topic!r} ({error})")
    return _topic_cache[key]


# ---------- CLI: preview the translations ----------
if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--topic":
        import digest  # noqa: F401  (loads .env for the Kimi key)
        from digest.config import CONFIG_FILE
        import yaml
        with open(CONFIG_FILE) as f:
            text, tree = from_topic(args[1], (yaml.safe_load(f) or {}).get("model", "kimi-k2.6"))
        print(f"Kimi's query:     {text}\n")
    elif len(args) == 1:
        try:
            tree = parse(args[0])
        except QueryError as e:
            sys.exit(f"Invalid query: {e}")
    else:
        sys.exit('Usage: python -m digest.query \'"a phrase" AND (b OR c)\'   or   '
                 'python -m digest.query --topic "plain-English topic"')
    for source, fn in RENDERERS.items():
        print(f"{source:<17} {fn(tree)}")
