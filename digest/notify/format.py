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
