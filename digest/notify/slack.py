"""Slack incoming webhook."""
import requests

from digest import paper
from digest.notify.format import (CONNECTIONS_TITLE, ZH_LABEL, connection_lines, date_range, digest_title,
                                  impact_line, stats_line)

NAME = "Slack"


def esc(text):
    """Escape characters Slack treats specially."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(top, sub, context=None):
    """The digest as Slack mrkdwn: one message."""
    context = context or {}
    lines = [f":newspaper: *{esc(digest_title(sub))}*\n"
             f"{esc(date_range(sub))} · {esc(stats_line(top, context))}\n"]
    if context.get("overview"):
        zh = f"\n{ZH_LABEL}{esc(context['overview_zh'])}" if context.get("overview_zh") else ""
        lines.append(f"*Overview:* {esc(context['overview'])}{zh}\n")
    for p in top:
        zh = f"{ZH_LABEL}{esc(p['summary_zh'])}\n" if p.get("summary_zh") else ""
        lines.append(f"*<{paper.url(p)}|{esc(p['title'])}>*\n"
                     f"_{esc(impact_line(p))}_\n"
                     f"{esc(p['summary'])}\n"
                     f"{zh}")
    if context.get("connections"):
        lines.append(f"*{CONNECTIONS_TITLE}*\n" + "\n".join(esc(x) for x in connection_lines(context["connections"])))
    return ["\n".join(lines)]


def send(url, text):
    r = requests.post(url, json={"text": text}, timeout=30)
    r.raise_for_status()
