"""WeCom (企业微信) group-bot webhook."""
import requests

from digest import paper
from digest.notify.format import (CONNECTIONS_TITLE, ZH_LABEL, connection_lines, date_range, digest_title,
                                  impact_line, stats_line)

NAME = "WeCom"
MAX_BYTES = 4096                        # WeCom rejects longer markdown messages


def build(top, sub, context=None):
    """The digest in WeCom markdown, packed into as few messages as its size limit allows."""
    context = context or {}
    head = (f"📰 **{digest_title(sub)}**\n"
            f'<font color="comment">{date_range(sub)} · {stats_line(top, context)}</font>')
    if context.get("overview"):
        head += f"\n\n**Overview:** {context['overview']}"
        if context.get("overview_zh"):
            head += f"\n{ZH_LABEL}{context['overview_zh']}"
    blocks = [head]
    for p in top:
        title = p["title"].replace("[", "").replace("]", "")   # brackets would break the [title](url) link
        zh = f"\n{ZH_LABEL}{p['summary_zh']}" if p.get("summary_zh") else ""
        blocks.append(f"[{title}]({paper.url(p)})\n"
                      f'<font color="comment">{impact_line(p)}</font>\n'
                      f"{p['summary']}{zh}")
    if context.get("connections"):
        blocks.append(f"**{CONNECTIONS_TITLE}**\n" + "\n".join(connection_lines(context["connections"])))
    messages = []
    for b in blocks:
        if messages and len((messages[-1] + "\n\n" + b).encode()) <= MAX_BYTES:
            messages[-1] += "\n\n" + b
        else:                                                   # (cuts a single block that's too long)
            messages.append(b.encode()[:MAX_BYTES].decode(errors="ignore"))
    return messages


def send(url, text):
    r = requests.post(url, json={"msgtype": "markdown", "markdown": {"content": text}}, timeout=30)
    r.raise_for_status()
    if r.json().get("errcode") != 0:            # WeCom reports errors in the reply, with HTTP 200
        raise RuntimeError(f"WeCom error: {r.json()}")
