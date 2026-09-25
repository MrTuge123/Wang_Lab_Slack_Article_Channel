"""Pieces of the digest shared by every chat."""


def impact_line(p):
    """'Journal · top author: Name (first, h=40) · keywords: GNN · score 0.72'"""
    bits = [p["journal"]]
    if p.get("top_author"):
        a = p["top_author"]
        bits.append(f"top author: {a['name']} ({a['role']}, h={a['h']})")
    if p["keyword_hits"]:
        bits.append("keywords: " + ", ".join(p["keyword_hits"]))
    bits.append(f"score {p['score']:.2f}")
    return " · ".join(bits)
