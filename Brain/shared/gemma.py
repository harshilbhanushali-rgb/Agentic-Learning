from __future__ import annotations
import json
import os
import time


class GemmaError(Exception):
    pass


class _ModelExhausted(Exception):
    """Internal signal: current model+key combo is done, try the next one in the chain."""


# The default model for every Gemma call, changed 2026-08-13 from "gemma-4-31b-it".
# gemma-4-31b-it's 16k tokens-per-minute ceiling could not fit the prompts this pipeline
# now sends -- one situated-describe call burned 8+ minutes of backoff before making any
# progress -- so the trial had to pass a flash-lite override per call site. Making it the
# default removes that per-call-site override.
#
# THIS CHANGES PRODUCTION OUTPUT, and every historical number in CLAUDE.md was produced
# under gemma-4-31b-it. Cross-run comparisons against them are model-confounded exactly the
# way arm0_baseline (1.58) vs arm0r_legacy_regen (1.04) already is -- do not read a
# difference against an old baseline as a change in anything but the model until a
# same-model baseline is re-run.
_DEFAULT_MODEL = "gemini-3.5-flash-lite"
_DEFAULT_FALLBACK_MODELS = ("gemini-3.1-flash-lite", "gemma-4-31b-it")

# The model that answered the most recent successful call_gemma, set by _call_once.
# Read it immediately after a call -- it is overwritten by the next one. Exists because
# the model chain downgrades silently on a rate limit, so the caller cannot otherwise
# know whether a strong model or a flash-lite fallback produced the result it is about
# to persist.
LAST_MODEL_USED: str | None = None

# Rate/quota-limit errors (RPM/TPM/RPD) — skip backoff, jump straight to the next model.
_LIMIT_MARKERS = ["429", "resource_exhausted", "quota", "rate limit"]
# Transient errors — keep the original same-model exponential-backoff retry.
_TRANSIENT_MARKERS = ["500", "503", "504", "disconnect", "remote protocol",
                      "connection", "timeout", "timed out", "deadline", "unavailable", "internal"]


def _fallback_enabled(override: bool | None) -> bool:
    if override is not None:
        return override
    return os.environ.get("MODEL_FALLBACK_ENABLED", "true").strip().lower() not in ("false", "0", "no")


def _call_once(
    prompt: str,
    api_key: str,
    model: str,
    temperature: float,
    max_output_tokens: int,
    max_retries: int,
    escalate: bool,
) -> dict:
    import httpx
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=180_000),  # 3-minute HTTP timeout
    )

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                ),
            )
            text = response.text.strip()
            parsed = json.loads(text)
            # Record which model actually answered. The chain silently downgrades on a
            # rate limit, so without this a stored verdict has unknown provenance -- and
            # "was this scored by the strong model or a flash-lite fallback?" is exactly
            # the question that made three separate 0%-hit-rate measurements
            # uninterpretable. Module-level rather than threaded through the return value
            # because every caller does result.get(...) on the parsed JSON and an injected
            # key would collide with real fields; safe because this pipeline is strictly
            # sequential.
            global LAST_MODEL_USED
            LAST_MODEL_USED = model
            return parsed
        except json.JSONDecodeError as e:
            raise GemmaError(f"Gemma returned non-JSON: {e}\nRaw: {text[:500]}")
        except Exception as e:
            err_str = str(e).lower()
            is_limit = any(code in err_str for code in _LIMIT_MARKERS)
            # Raw network-transport drops (SSL read errors, connect timeouts,
            # protocol resets) surface with all sorts of wording depending on
            # the OS/socket layer -- "_ssl.c:2580" told us nothing string
            # matching could reliably anticipate. httpx.TransportError is the
            # base class for every one of those (ReadError, ConnectError,
            # ConnectTimeout, RemoteProtocolError, ...), so check the type
            # directly instead of extending the marker list forever.
            is_transient = (
                any(code in err_str for code in _TRANSIENT_MARKERS)
                or isinstance(e, httpx.TransportError)
            )

            if escalate and is_limit:
                print(f"[gemma] {model} hit a rate/quota limit. Escalating to next model/key...")
                raise _ModelExhausted(str(e)) from e

            if attempt < max_retries - 1 and (is_transient or is_limit):
                wait = 2 ** (attempt + 1)
                print(f"[gemma] Transient error on {model} (attempt {attempt+1}). Waiting {wait}s...")
                time.sleep(wait)
                continue

            if escalate and (is_transient or is_limit):
                print(f"[gemma] {model} exhausted its retries. Escalating to next model/key...")
                raise _ModelExhausted(str(e)) from e

            raise GemmaError(f"Gemma API error: {e}") from e

    if escalate:
        raise _ModelExhausted(f"{model}: max retries exceeded")
    raise GemmaError("Max retries exceeded")


def call_gemma(
    prompt: str,
    api_key,
    *,
    model: str = _DEFAULT_MODEL,
    temperature: float = 0.2,
    max_output_tokens: int = 8192,
    max_retries: int = 5,
    fallback_enabled: bool | None = None,
    fallback_models: tuple = _DEFAULT_FALLBACK_MODELS,
) -> dict:
    """Call Gemma/Gemini via Google AI Studio. Forces JSON output. Retries on 429/503.

    `api_key` may be a single key (str) or an ordered sequence of keys to rotate
    through. When MODEL_FALLBACK_ENABLED is on (default), a rate/quota-limit error
    escalates through `fallback_models` on the current key before rotating to the
    next key and restarting the chain from `model`. Set MODEL_FALLBACK_ENABLED=false
    (or pass fallback_enabled=False) to restore the original single-model,
    single-key retry-only behavior.
    """
    keys = [api_key] if isinstance(api_key, str) else list(api_key)
    if not keys:
        raise GemmaError("call_gemma requires at least one API key")

    escalate = _fallback_enabled(fallback_enabled)
    models_chain = [model, *fallback_models] if escalate else [model]

    last_err: Exception | None = None
    for key_idx, key in enumerate(keys):
        for m in models_chain:
            try:
                return _call_once(prompt, key, m, temperature, max_output_tokens, max_retries, escalate)
            except _ModelExhausted as e:
                last_err = e
                continue
        if escalate and key_idx < len(keys) - 1:
            print(f"[gemma] Exhausted all models on key #{key_idx + 1}. Rotating to key #{key_idx + 2}...")

    raise GemmaError(f"Gemma API error: all models/keys exhausted. Last error: {last_err}")
