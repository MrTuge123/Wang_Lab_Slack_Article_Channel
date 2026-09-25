"""Send a subscriber's digest to every chat switched on under its outputs:.

Each chat is a module here with NAME, build(top, sub) -> [message text] and send(url, text).
To add one (e.g. email): write the module and add it to CHATS.
"""
import json
import os

import requests

from digest.notify import slack, wecom

CHATS = {"slack": slack, "wecom": wecom}     # key under outputs: in a subscriber file -> module


def webhook_url(env_name):
    """The URL stored under env_name: from .env / the environment, else from the GitHub secrets the
    workflow passes in as JSON (so a new subscriber needs only a new secret, not a workflow edit).
    GitHub stores secret names in upper case."""
    if not env_name:
        return None
    if os.getenv(env_name):
        return os.getenv(env_name)
    try:
        secrets = json.loads(os.getenv("GITHUB_SECRETS_JSON") or "{}")
    except ValueError:
        secrets = {}
    return secrets.get(env_name.upper())


def post(top, sub, dry_run=False):
    """Post the digest to the subscriber's chats. Returns (posted, failed) chat names.
    With dry_run, prints the messages instead of sending them."""
    outputs = sub.get("outputs") or {}
    if (outputs.get("email") or {}).get("enabled"):
        print("Note: email is on, but sending email isn't built yet, so no email was sent.")
    keys = [k for k in CHATS if (outputs.get(k) or {}).get("enabled")]
    if not keys:
        raise RuntimeError(f"nowhere to post: turn on outputs.slack and/or outputs.wecom in {sub['file']}")
    posted, failed = [], []
    for key in keys:
        chat = CHATS[key]
        env = outputs[key].get("webhook_env")
        url = webhook_url(env)
        if not (dry_run or url):                # switched on, but nowhere to send it
            print(f"Warning: {chat.NAME} is switched on, but {env or 'its webhook_env'} isn't set "
                  f"(.env locally, GitHub secret in Actions)")
            failed.append(chat.NAME)
            continue
        messages = chat.build(top, sub)
        try:
            for i, text in enumerate(messages, 1):
                if dry_run:
                    print(f"----- DRY RUN: would post to {chat.NAME} ({i}/{len(messages)}) -----\n{text}\n")
                else:
                    chat.send(url, text)
            posted.append(chat.NAME)
        except (requests.RequestException, RuntimeError) as e:   # keep going: the other chat still gets it
            print(f"Warning: posting to {chat.NAME} failed ({e})")
            failed.append(chat.NAME)
    return posted, failed
