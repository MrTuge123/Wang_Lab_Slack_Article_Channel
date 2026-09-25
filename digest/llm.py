"""Kimi (Moonshot's OpenAI-compatible API): one client and rate-limit retries for every use."""
import os
import time

from openai import OpenAI, RateLimitError

_client = None


class RateLimited(RuntimeError):
    pass


def _kimi():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("MOONSHOT_API_KEY"), base_url="https://api.moonshot.ai/v1")
    return _client


def ask(system, user, model):
    """One chat completion. Retries with waits on rate limits (new Kimi accounts allow
    only 3 requests/min); raises RateLimited if it never gets through."""
    for attempt in range(5):
        try:
            r = _kimi().chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            return r.choices[0].message.content.strip()
        except RateLimitError:
            wait = 20 * (attempt + 1)
            print(f"  Kimi rate limit hit, waiting {wait}s...")
            time.sleep(wait)
    raise RateLimited("Kimi rate limit: gave up after 5 tries")
