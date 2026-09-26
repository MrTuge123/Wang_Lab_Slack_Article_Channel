"""Slack incoming webhook."""
import requests

from digest import paper
from digest.notify.format import ZH_LABEL, impact_line

NAME = "Slack"


def esc(text):
    """Escape characters Slack treats specially."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(top, sub, context=None):
    """The digest as Slack mrkdwn: one message."""
    lines = [f":newspaper: *New papers* for {esc(sub['name'])} "
             f"(last {sub['days_back']} days)\n"]
    for p in top:
        zh = f"{ZH_LABEL}{esc(p['summary_zh'])}\n" if p.get("summary_zh") else ""
        lines.append(f"*<{paper.url(p)}|{esc(p['title'])}>*\n"
                     f"_{esc(impact_line(p))}_\n"
                     f"{esc(p['summary'])}\n"
                     f"{zh}")
    return ["\n".join(lines)]


def send(url, text):
    r = requests.post(url, json={"text": text}, timeout=30)
    r.raise_for_status()
