"""The LLM (any OpenAI-compatible API): one client and rate-limit retries for every use.

config.yaml's provider: picks the API; model: picks the model on it.
    kimi   Moonshot (MOONSHOT_API_KEY), e.g. model: kimi-k2.6
    groq   Groq (GROQ_API_KEY), e.g. model: openai/gpt-oss-120b
Groq's free tier caps tokens per minute (tpm below, 8K for gpt-oss-120b) and counts each request's
max_tokens against it, so on Groq max_tokens is shrunk to fit what's left after the prompt."""
import json
import os
import time

import yaml
from openai import OpenAI, RateLimitError

PROVIDERS = {
    "kimi": {"name": "Kimi", "key": "MOONSHOT_API_KEY", "base_url": "https://api.moonshot.ai/v1"},
    "groq": {"name": "Groq", "key": "GROQ_API_KEY", "base_url": "https://api.groq.com/openai/v1",
             "tpm": 8000, "reasoning_effort": "low"},
}
CHARS_PER_TOKEN = 3.5           # rough prompt size estimate (English); kept low to err on the safe side

_client = None
_always_thinks = set()           # models that refused thinking=False (they answer with reasoning)
_provider = None


class RateLimited(RuntimeError):
    pass


def provider():
    """This run's provider settings (config.yaml's provider:, default kimi; LLM_PROVIDER overrides)."""
    global _provider
    if _provider is None:
        name = os.getenv("LLM_PROVIDER")
        if not name:
            try:
                with open("config.yaml") as f:
                    name = (yaml.safe_load(f) or {}).get("provider")
            except OSError:
                pass
        name = (name or "kimi").lower()
        if name not in PROVIDERS:
            raise ValueError(f"unknown provider {name!r} (use one of: {', '.join(PROVIDERS)})")
        _provider = PROVIDERS[name]
    return _provider


def name():
    return provider()["name"]


def _llm():
    global _client
    if _client is None:
        p = provider()
        if not os.getenv(p["key"]):
            raise RuntimeError(f"{p['key']} is not set (in .env or the GitHub secrets)")
        _client = OpenAI(api_key=os.getenv(p["key"]), base_url=p["base_url"])
    return _client


def _options(model, system, user, max_tokens):
    """Extra request options for this provider: max_tokens (fitted to Groq's per-minute budget)
    and a lower reasoning effort for gpt-oss models, which otherwise spend most of it thinking."""
    p, extra = provider(), {}
    if p.get("tpm"):
        prompt = int((len(system) + len(user)) / CHARS_PER_TOKEN) + 100
        room = p["tpm"] - prompt
        max_tokens = max(1024, min(max_tokens or room, room))
    if max_tokens:
        extra["max_tokens"] = max_tokens
    if p.get("reasoning_effort") and "gpt-oss" in model:
        extra["reasoning_effort"] = p["reasoning_effort"]
    return extra


def _wait(err, attempt):
    """Seconds to wait after a rate limit: the server's retry-after if it gives one, else 20, 40, ..."""
    try:
        return min(90, max(1, int(float(err.response.headers.get("retry-after")))) + 1)
    except (AttributeError, TypeError, ValueError):
        return 20 * (attempt + 1)


def _complete(system, user, model, max_tokens=None):
    """(reply text, finish_reason) of one chat completion. Retries with waits on rate limits
    (new Kimi accounts allow only 3 requests/min; Groq's free tier ~8K tokens/min);
    raises RateLimited if it never gets through.
    thinking=False asks the model to answer without reasoning first: ~25x faster and far fewer
    tokens for simple judgments. A model that can't do that answers with reasoning instead."""
    extra = _options(model, system, user, max_tokens)
    if not thinking and model not in _always_thinks:
        extra["extra_body"] = {"thinking": {"type": "disabled"}}
    for attempt in range(5):
        try:
            r = _llm().chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                **extra,
            )
            return (r.choices[0].message.content or "").strip(), r.choices[0].finish_reason
        except RateLimitError as e:
            wait = _wait(e, attempt)
            print(f"  {name()} rate limit hit, waiting {wait}s...")
            time.sleep(wait)
    raise RateLimited(f"{name()} rate limit: gave up after 5 tries")


def ask(system, user, model, max_tokens=None, thinking=True):
    """One chat completion's reply text."""
    return _complete(system, user, model, max_tokens, thinking)[0]


def parse_json(text):
    """The JSON object in a reply, ignoring ``` fences or words around it. Raises ValueError."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    obj = json.loads(text[start:end + 1])          # JSONDecodeError is a ValueError
    if not isinstance(obj, dict):
        raise ValueError("the reply's JSON isn't an object")
    return obj


def ask_json(system, user, model, tries=2, max_tokens=32768, thinking=True):
    """A reply that is one JSON object (a dict). Asks again if the reply isn't valid JSON; raises
    ValueError if it never is (callers then fall back to smaller requests). max_tokens is generous
    because a thinking model's reasoning counts against it: too low and the answer is cut off or empty.
    (On Groq it's shrunk to fit the per-minute token budget.)"""
    err = None
    for attempt in range(tries):
        text, finish = _complete(system, user, model, max_tokens, thinking)
        try:
            if not text:
                raise ValueError(f"empty reply, finish_reason={finish}")
            return parse_json(text)
        except ValueError as e:
            cut = " (cut off: hit max_tokens)" if finish == "length" else ""
            err = f"{e}{cut}; reply began: {text[:150]!r}" if text else f"{e}{cut}"
            if attempt < tries - 1:
                print(f"  {name()}'s reply wasn't valid JSON ({err}); asking again...")
    raise ValueError(f"no valid JSON from {name()} ({err})")
