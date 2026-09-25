"""Send a subscriber's digest to every chat switched on under its outputs:.

Each chat is a module here with NAME, build(top, sub) -> [messages] and send(destination, message).
Optional: destination(settings) -> (destination, None) or (None, what's missing)  [default: the
webhook URL named by webhook_env], and preview(message) -> text for --dry-run [default: str].
To add one: write the module and add it to CHATS.
"""
import requests

from digest import env
from digest.notify import mail, slack, wecom

CHATS = {"slack": slack, "wecom": wecom, "email": mail}   # key under outputs: -> module


def _webhook_destination(cfg):
    name = cfg.get("webhook_env")
    url = env.get(name)
    return (url, None) if url else (None, f"{name or 'its webhook_env'} isn't set (.env locally, GitHub secret in Actions)")


def post(top, sub, dry_run=False):
    """Post the digest to the subscriber's chats. Returns (posted, failed) chat names.
    With dry_run, prints the messages instead of sending them."""
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
        messages = chat.build(top, sub)
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
