"""Read a secret by name: from .env / the environment, else from the GitHub secrets the workflow
passes in as JSON (GITHUB_SECRETS_JSON), so new secrets need no workflow edit.
GitHub stores secret names in upper case."""
import json
import os


def get(name):
    if not name:
        return None
    if os.getenv(name):
        return os.getenv(name)
    try:
        secrets = json.loads(os.getenv("GITHUB_SECRETS_JSON") or "{}")
    except ValueError:
        secrets = {}
    return secrets.get(name.upper())
