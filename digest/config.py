"""Settings: config.yaml holds shared defaults; each subscribers/<id>.yaml overrides them."""
import copy
import glob
import os
import re
import sys

import yaml

CONFIG_FILE = "config.yaml"
SUBSCRIBERS_DIR = "subscribers"


def _deep_merge(base, over):
    """base with over's values on top; nested dicts (like ranking:) are merged key by key."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_subscribers(only=None):
    """Each subscribers/<id>.yaml layered over config.yaml. Files starting with _ are skipped.
    Each subscriber also gets "id" (its file name), "file", "name" and a "ranking" dict."""
    with open(CONFIG_FILE) as f:
        shared = yaml.safe_load(f) or {}
    subs = []
    for path in sorted(glob.glob(os.path.join(SUBSCRIBERS_DIR, "*.yaml"))):
        sid = os.path.splitext(os.path.basename(path))[0]
        if sid.startswith("_") or (only and sid != only):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
            sys.exit(f"{path}: use only letters, digits, - and _ in subscriber file names")
        with open(path) as f:
            sub = _deep_merge(shared, yaml.safe_load(f) or {})
        if not sub.get("query"):
            sys.exit(f"{path}: 'query' is missing")
        sub["id"] = sid
        sub["file"] = path
        sub.setdefault("name", sid)
        sub["ranking"] = sub.get("ranking") or {}
        subs.append(sub)
    if only and not subs:
        sys.exit(f"No subscriber '{only}' (expected {SUBSCRIBERS_DIR}/{only}.yaml)")
    if not subs:
        sys.exit(f"No subscribers: copy {SUBSCRIBERS_DIR}/_template.yaml to {SUBSCRIBERS_DIR}/<name>.yaml")
    return subs
