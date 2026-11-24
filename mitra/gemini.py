"""Small wrapper around the Gemini API (google-genai package)."""
import json
import logging
import os
import re
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

# Change this in your Codespace if Google releases a newer model:
#   export GEMINI_MODEL="gemini-3.5-flash"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
# Each model has its own free-tier quota. If one is used up or busy we try the next.
FALLBACKS = [m.strip() for m in os.environ.get(
    "GEMINI_FALLBACK_MODELS",
    "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-flash-lite-latest,gemini-2.5-flash").split(",") if m.strip()]
_exhausted: dict[tuple, float] = {}   # (model, kind) -> time it ran out (skip it for a while)

_client = None


def client() -> genai.Client:
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it as a Codespaces secret "
                "(get a key at aistudio.google.com/apikey)."
            )
        try:  # never hang: 45 s per request, no hidden retries (we fall back to the next model instead)
            opts = types.HttpOptions(api_version="v1beta", timeout=45_000,
                                     retry_options=types.HttpRetryOptions(attempts=1))
        except Exception:  # older google-genai without these options
            opts = types.HttpOptions(api_version="v1beta", timeout=45_000)
        _client = genai.Client(api_key=key, http_options=opts)
    return _client


FAST_MODELS = [m for m in FALLBACKS if "lite" in m]  # quicker models for simple reading/scoring jobs


def generate(contents, config, fast: bool = False):
    """generate_content with model fallback when a model's quota is used up.

    fast=True tries the quicker 'lite' models first (used for scoring headlines and short summaries)."""
    kind = "search" if getattr(config, "tools", None) else "plain"  # search calls have their own quota
    order = [*FAST_MODELS, MODEL, *FALLBACKS] if fast else [MODEL, *FALLBACKS]
    models = [m for m in dict.fromkeys(order)
              if time.time() - _exhausted.get((m, kind), 0) > 15 * 60] or [MODEL]
    last_err = None
    started = time.time()
    for model in models:
        if time.time() - started > 90:  # don't keep a learner waiting: callers fall back to rules
            break
        try:
            return client().models.generate_content(model=model, contents=contents, config=config)
        except Exception as err:
            if not isinstance(err, genai_errors.APIError):  # timeout / network: try the next model
                logging.warning("Gemini model %s failed (%s), trying the next one", model, err)
                last_err = err
                continue
            # 429 quota, 404 retired model, 5xx overloaded
            if getattr(err, "code", None) not in (429, 404, 500, 503):
                raise
            logging.warning("Gemini model %s unavailable (%s), trying the next one", model, err.code)
            _exhausted[(model, kind)] = time.time()
            last_err = err
    raise last_err or TimeoutError("Gemini took too long")


def upload(path: str):
    """Upload a PDF so Gemini can read it."""
    return client().files.upload(file=path)


def ask_json(prompt: str, files: list | None = None, fast: bool = False) -> dict | list:
    """Ask Gemini and get JSON back."""
    contents = [*(files or []), prompt]
    resp = generate(contents, types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.2,
    ), fast=fast)
    return json.loads(resp.text)


def ask_web(prompt: str) -> tuple[dict | list | None, list[dict]]:
    """Ask Gemini with live Google Search. Returns (parsed JSON or None, sources)."""
    resp = generate(
        prompt + "\n\nAnswer ONLY with JSON inside a ```json code block.",
        types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
        ),
    )
    text = resp.text or ""
    data = None
    match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    try:
        data = json.loads(match.group(1) if match else text)
    except (json.JSONDecodeError, AttributeError):
        data = None

    sources = []
    try:
        for chunk in resp.candidates[0].grounding_metadata.grounding_chunks or []:
            if chunk.web:
                sources.append({"title": chunk.web.title, "url": chunk.web.uri})
    except (AttributeError, IndexError, TypeError):
        pass
    return data, sources
