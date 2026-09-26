"""Send a subscriber's digest to every chat switched on under its outputs:.

Each chat is a module here with NAME, build(top, sub, context) -> [messages] and send(destination, message).
Optional: destination(settings) -> (destination, None) or (None, what's missing)  [default: the
webhook URL named by webhook_env], and preview(message) -> text for --dry-run [default: str].
To add one: write the module and add it to CHATS.

A paper's p["summary_zh"] (Chinese translation of the summary) reaches build() only for chats
with chinese_summary: true; for the others it's None, so build() just shows it when it's there.
"""
import requests

from digest import env
from digest.notify import mail, slack, wecom

CHATS = {"slack": slack, "wecom": wecom, "email": mail}   # key under outputs: -> module


def _webhook_destination(cfg):
    name = cfg.get("webhook_env")
    url = env.get(name)
    return (url, None) if url else (None, f"{name or 'its webhook_env'} isn't set (.env locally, GitHub secret in Actions)")


def wants_chinese(sub):
    """True if any chat that's switched on has chinese_summary: true."""
    outputs = sub.get("outputs") or {}
    return any((outputs.get(k) or {}).get("enabled") and (outputs.get(k) or {}).get("chinese_summary")
               for k in CHATS)


def post(top, sub, dry_run=False, context=None):
    """Post the digest to the subscriber's chats. Returns (posted, failed) chat names.
    With dry_run, prints the messages instead of sending them. context: run stats for the
    message ({"candidates": int, "found": {source: count}}), optional."""
    outputs = sub.get("outputs") or {}
    keys = [k for k in CHATS if (outputs.get(k) or {}).get("enabled")]
    if not keys:
        raise RuntimeError(f"nowhere to post: turn on outputs.slack, outputs.wecom or outputs.email in {sub['file']}")
    posted, failed = [], []
    for key in keys:
        chat = CHATS[key]
        dest, problem = getattr(chat, "destination", _webhook_destination)(outputs[key])
        if problem and not dry_run:                 # switched on, but can't be sent
            print(f"Warning: {chat.NAME} is switched on, but {problem}")
            failed.append(chat.NAME)
            continue
        papers = top if outputs[key].get("chinese_summary") else [{**p, "summary_zh": None} for p in top]
        messages = chat.build(papers, sub, context)
        preview = getattr(chat, "preview", str)
        try:
            for i, message in enumerate(messages, 1):
                if dry_run:
                    note = f" [not sendable yet: {problem}]" if problem else ""
                    print(f"----- DRY RUN: would post to {chat.NAME} ({i}/{len(messages)}){note} -----\n"
                          f"{preview(message)}\n")
                else:
                    chat.send(dest, message)
            posted.append(chat.NAME)
        except (requests.RequestException, RuntimeError, OSError) as e:   # keep going: other chats still get it
            print(f"Warning: posting to {chat.NAME} failed ({e})")
            failed.append(chat.NAME)
    return posted, failed
