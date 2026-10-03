"""Kimi (Moonshot's OpenAI-compatible API): one client and rate-limit retries for every use."""
import json
import os
import time

from openai import BadRequestError, OpenAI, RateLimitError

_client = None
_always_thinks = set()           # models that refused thinking=False (they answer with reasoning)


class RateLimited(RuntimeError):
    pass


def _kimi():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("MOONSHOT_API_KEY"), base_url="https://api.moonshot.ai/v1")
    return _client


def _complete(system, user, model, max_tokens=None, thinking=True):
    """(reply text, finish_reason) of one chat completion. Retries with waits on rate limits
    (new Kimi accounts allow only 3 requests/min); raises RateLimited if it never gets through.
    thinking=False asks the model to answer without reasoning first: ~25x faster and far fewer
    tokens for simple judgments. A model that can't do that answers with reasoning instead."""
    extra = {"max_tokens": max_tokens} if max_tokens else {}
    if not thinking and model not in _always_thinks:
        extra["extra_body"] = {"thinking": {"type": "disabled"}}
    for attempt in range(5):
        try:
            r = _kimi().chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                **extra,
            )
            return (r.choices[0].message.content or "").strip(), r.choices[0].finish_reason
        except RateLimitError:
            wait = 20 * (attempt + 1)
            print(f"  Kimi rate limit hit, waiting {wait}s...")
            time.sleep(wait)
        except BadRequestError as e:
            if "extra_body" not in extra or "thinking" not in str(e):
                raise
            print(f"  {model} can't answer without reasoning; using reasoning.")
            _always_thinks.add(model)
            del extra["extra_body"]
    raise RateLimited("Kimi rate limit: gave up after 5 tries")


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
    because a thinking model's reasoning counts against it: too low and the answer is cut off or empty."""
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
                print(f"  Kimi's reply wasn't valid JSON ({err}); asking again...")
    raise ValueError(f"no valid JSON from Kimi ({err})")
