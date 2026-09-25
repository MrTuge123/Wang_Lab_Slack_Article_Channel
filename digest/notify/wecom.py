"""WeCom (企业微信) group-bot webhook."""
import requests

from digest import paper
from digest.notify.format import impact_line

NAME = "WeCom"
MAX_BYTES = 4096                        # WeCom rejects longer markdown messages


def build(top, sub):
    """The digest in WeCom markdown, packed into as few messages as its size limit allows."""
    blocks = [f"📰 **New papers** for {sub['name']} (last {sub['days_back']} days)"]
    for p in top:
        title = p["title"].replace("[", "").replace("]", "")   # brackets would break the [title](url) link
        blocks.append(f"[{title}]({paper.url(p)})\n"
                      f'<font color="comment">{impact_line(p)}</font>\n'
                      f"{p['summary']}")
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
