"""Pieces of the digest shared by every chat."""
import datetime as dt

ZH_LABEL = "中文概要："                  # before the Chinese summary (摘要 would read as "abstract")


def digest_title(sub):
    """'Wang Lab · paper digest': the first line of every chat's digest."""
    return f"{sub['name']} · paper digest"


def period(sub):
    """'the last 30 days': how far back the search went (days_back)."""
    n = sub["days_back"]
    return "the last day" if n == 1 else f"the last {n} days"


def date_range(sub):
    """'Aug 27 – Sep 26, 2026': the days searched, ending today."""
    end = dt.date.today()
    start = end - dt.timedelta(days=sub["days_back"])
    fmt = lambda d: f"{d:%b} {d.day}"
    return f"{fmt(start)} – {fmt(end)}, {end.year}"


def stats_line(top, context=None):
    """'5 new papers, picked from 48 candidates'"""
    n = len(top)
    s = f"{n} new paper{'s' * (n != 1)}"
    if (context or {}).get("candidates"):
        s += f", picked from {context['candidates']} candidates"
    return s


CONNECTIONS_TITLE = "Connections to your earlier papers"


def _clip(text, n):
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _day(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def connection_lines(c):
    """The Connections section (digest/connections.py) as plain-text lines, without its title;
    each chat adds its own markup."""
    n, lines = c["papers"], []
    if c["shared"]:
        lines.append(f"{'This paper shares' if n == 1 else f'These {n} papers share'} {c['n_shared']} "
                     f"reference{'s' * (c['n_shared'] != 1)} with {c['linked']} earlier "
                     f"paper{'s' * (c['linked'] != 1)} in your history. Most shared:")
        for s in c["shared"]:
            year = f" ({s['year']})" if s.get("year") else ""
            lines.append(f"• {_clip(s['title'], 90)}{year}: cited by {s['now']} of "
                         f"{'it' if n == 1 else 'these'} and {s['earlier']} earlier")
    if c["direct"]:
        lines.append(f"Direct citations of earlier papers ({c['n_direct']}):")
        for d in c["direct"]:
            how = f"sent to you on {_day(d['date'])}" if d["sent"] else f"a candidate on {_day(d['date'])}, not sent"
            lines.append(f"• “{_clip(d['citing'], 60)}” cites “{_clip(d['title'], 70)}” ({how})")
    if c["with_refs"] < n:
        lines.append(f"({c['with_refs']} of {n} papers have reference data so far.)")
    return lines


def impact_line(p):
    """'Journal · top author: Name (first, h=40) · keywords: GNN · relevance 8/10 · score 0.72'"""
    bits = [p["journal"]]
    if p.get("top_author"):
        a = p["top_author"]
        bits.append(f"top author: {a['name']} ({a['role']}, h={a['h']})")
    if p["keyword_hits"]:
        bits.append("keywords: " + ", ".join(p["keyword_hits"]))
    if p.get("relevance") is not None:
        bits.append(f"relevance {p['relevance']}/10")
    bits.append(f"score {p['score']:.2f}")
    return " · ".join(bits)
