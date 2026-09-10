"""The Joveo LLM gateway transport — chat and embeddings — in one place.

MOVED HERE FROM `calibration/trial_gateway.py` ON 2026-08-19, and the direction matters.
The rule this project holds is that **nothing in `v1/`, `v2/`, `shared/` or `preprocessing/`
may import `calibration/`** — calibration is the measurement tooling, not the pipeline. So
once production needed the gateway (see `preprocessing/embedder.py`'s `gateway` backend), the
transport had to move down here and calibration had to import it back, exactly as
`v2/layer_c.build_clause_pool`, `shared/response_taxonomy.py` and `shared/relative_match.py`
each did before it. `calibration/trial_gateway.py` re-exports every name from this module, so
its own callers are unchanged and its self-test still measures the real transport.

WHY PRODUCTION NEEDS THIS AT ALL. `tuning.yaml`'s `embedding.backend: gemini` routes to the
DIRECT Google AI Studio API at ~1k requests/day, NOT to the gateway — and the two keep
different caches under different key schemes. The taxonomy, every trigger and every response
clause in this corpus were paid for THROUGH THE GATEWAY into `gemini_embed_cache.db`. Flipping
to `gemini` would therefore re-pay for all of them at 1k/day. The `gateway` backend exists so
that switch is nearly free instead.

*** THE TWO NON-OBVIOUS FACTS ABOUT THIS ENDPOINT, BOTH MEASURED, BOTH LOAD-BEARING: ***

1. `/embeddings` SILENTLY RETURNS FEWER VECTORS THAN INPUTS, INTERMITTENTLY — HTTP 200,
   well-formed body, no warning. It is not content-determined: the identical request that
   collapsed five times running returned correctly minutes later from a fresh process. That
   is why `embed_one` sends ONE text per request and ASSERTS the count, and why
   `embed_batched` exists only to demonstrate and detect the hazard. NEVER BATCH THIS
   ENDPOINT.

2. The gateway caps `gemini-embedding-2` at 150 REQUESTS PER WINDOW PER KEY. The module-level
   `_RateLimiter` paces to 140/min and `penalise()` pushes every worker back on a 429, because
   the limit is per KEY — two clients in one process must draw from ONE bucket or they race
   each other into the same rejection. A rejected request still spends quota, so do not raise
   the pace without evidence.

Credentials come from `Brain/.env` (gitignored) as LLM_GATEWAY_URL / LLM_GATEWAY_KEY, never
from source. The gateway requires the Joveo VPN.

The full measurement record — including the `/v1` connect-timeout trap and the chat-completion
response caching that `no_cache=True` defeats — stays in `calibration/trial_gateway.py`'s
docstring, which is where it was established.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CHAT_MODEL = "gemini-3.5-flash-lite"
EMBED_MODEL = "gemini-embedding-2"

# Native width of gemini-embedding-2. Kept explicit rather than left to the server
# default so a cache key or a Pinecone index can never disagree with what was asked for.
EMBED_DIMENSIONS = 3072

_LIMIT_MARKERS = ("429", "resource_exhausted", "quota", "rate limit")
_TRANSIENT_MARKERS = ("500", "502", "503", "504", "timeout", "timed out",
                      "unavailable", "internal", "connection", "disconnect")



class GatewayError(Exception):
    pass


class _RateLimiter:
    """A shared token bucket pacing requests to a per-minute ceiling.

    *** MEASURED 2026-08-19: THE GATEWAY CAPS `gemini-embedding-2` AT 150 REQUESTS PER
    WINDOW PER KEY. *** ("Limit type: requests. Current limit: 150, Remaining: 0.") Nothing
    here paced requests before, so `embed(..., workers=20)` on a corpus-sized job fired a
    burst ~80x the allowance, took 429s on every thread at once, and then hard-failed —
    because the retry ladder waits 2+4+8 = 14 SECONDS against a ~60-second window and was
    arithmetically incapable of waiting it out.

    Every fetch this session before that one was <= 258 requests, i.e. under the ceiling, so
    the wall had never been reached and the transport's inability to handle it was invisible.

    Shared at MODULE level, not per client: the limit is per API KEY, so two GatewayClient
    instances in one process must draw from ONE bucket or they simply race each other into
    the same 429.
    """

    def __init__(self, per_minute: int) -> None:
        self._min_interval = 60.0 / max(1, per_minute)
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next - now
            if wait <= 0:
                self._next = now + self._min_interval
                wait = 0.0
            else:
                self._next += self._min_interval
        if wait > 0:
            time.sleep(wait)

    def penalise(self, seconds: float) -> None:
        """Push the whole bucket back after a 429, so EVERY worker waits, not just the one
        that got rejected. Without this the other threads keep hammering the endpoint that
        just said stop.

        *** TIME-BASED ONLY. AN EARLIER VERSION ALSO CUT THE RATE PERMANENTLY (x1.5 per
        rejection, no recovery) AND THAT WAS A PESSIMIZATION. *** Measured 2026-08-19 at a
        nominal 140/min: the endpoint sustained ~108 req/min effective THROUGH 14 rate-limit
        events in 3.6 minutes — the rejections were absorbed at acceptable cost and the job
        was on track for ~104 minutes. A permanent 1.5x cut per rejection would have driven
        that to the 17/min floor within the first minute and genuinely stalled it. 429s here
        are routine and recoverable, so they get a pause, not a demotion.
        """
        with self._lock:
            self._next = max(self._next, time.monotonic() + seconds)


# 140 against a 150/window ceiling. MEASURED, not guessed: at this pace the endpoint sustained
# ~108 req/min effective through 14 absorbed rate-limit events, i.e. rejections cost time but the
# job progresses. A rejected request DOES spend quota, which is why the nominal pace sits below
# the ceiling and why `penalise` pauses every worker rather than just the unlucky one.
# Overridable for a deliberately slower run on a busier key.
EMBED_PER_MINUTE = int(os.environ.get("BRAIN_GATEWAY_EMBED_RPM", "140"))
_embed_limiter = _RateLimiter(EMBED_PER_MINUTE)

# *** THE GATEWAY ENFORCES A SECOND, INDEPENDENT LIMIT: max_parallel_requests = 8. ***
# MEASURED 2026-08-19, and it is NOT the 150-requests-per-window cap already documented:
#
#   HTTP 429 ... "Limit type: max_parallel_requests. Current limit: 8, Remaining: 0."
#
# That is a CONCURRENCY ceiling, not a rate one, and the token bucket above does nothing about
# it -- the bucket controls how often a request STARTS, not how many are in flight at once.
# A corpus fetch run at workers=8 therefore sits exactly ON the ceiling for its whole life,
# with zero headroom, so any request the gateway has not finished releasing rejects the next
# one. It survived 70 minutes and 7,200 of 7,472 vectors that way before losing all four
# retries in a single window and hard-failing.
#
# The semaphore is the fix and the worker count is not: a caller can always pass workers=20,
# and every calibration script that predates this does. Clamping HERE means the transport is
# safe regardless of what any caller asks for. Module level, same reasoning as the rate
# limiter -- the limit is per API KEY, so two clients in one process must share one counter.
#
# 6 rather than 8 on purpose: retries are themselves requests, so the ceiling must not be the
# operating point. Override with BRAIN_GATEWAY_MAX_PARALLEL if a key's limit differs.
EMBED_MAX_PARALLEL = int(os.environ.get("BRAIN_GATEWAY_MAX_PARALLEL", "6"))
_embed_parallel = threading.Semaphore(EMBED_MAX_PARALLEL)

# Distinct from _LIMIT_MARKERS: a concurrency rejection clears the moment a sibling request
# finishes, so it wants a SHORT wait. Backing off 15/30/45s -- the ladder a quota rejection
# needs -- would idle every worker for a minute over a condition that resolves in
# milliseconds, and worse, it releases them all at the same instant to collide again.
_PARALLEL_MARKERS = ("max_parallel_requests", "max parallel")


def _jitter() -> float:
    """A deterministic-per-thread spread in [0, 1), without seeding `random` globally.

    The point of jitter here is only that sibling threads stop colliding, so any stable
    per-thread offset does the job; using the thread identity avoids touching module-level
    RNG state that a calibration harness may have seeded for reproducibility.
    """
    return (threading.get_ident() % 1000) / 1000.0


class GatewayClient:
    """Minimal OpenAI-compatible client for the Joveo gateway.

    Deliberately httpx rather than the `openai` SDK: openai is not installed in this
    venv, and the two endpoints used here are a plain POST each. Adding a dependency to
    a throwaway trial would be the expensive way to learn the same facts.

    One `httpx.Client` held for the object's lifetime -- per-call clients are the
    mistake `preprocessing/embedder.py` and `shared/pinecone_store.py` each already
    made, where a garbage-collected handle raises mid-request.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 timeout: float = 120.0, max_retries: int = 4):
        base_url = base_url or os.environ.get("LLM_GATEWAY_URL", "")
        api_key = api_key or os.environ.get("LLM_GATEWAY_KEY", "")
        if not base_url or not api_key:
            raise GatewayError(
                "Set LLM_GATEWAY_URL and LLM_GATEWAY_KEY in Brain/.env "
                "(this file keeps no credentials in source -- it is tracked, .env is not)."
            )
        # Trailing '/' or a '/v1' someone helpfully added both break this gateway; see
        # note 1 in the module docstring. Normalising here is cheaper than debugging a
        # 20-second connect timeout later.
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.max_retries = max_retries
        self._http = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GatewayClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- transport ---------------------------------------------------------------

    def _post(self, path: str, body: dict) -> dict:
        """POST with the same retry split gemma.py draws: back off on transient/limit,
        fail immediately on anything else. A 4xx that is not a rate limit means the
        request is wrong and retrying it just wastes the same call five times."""
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = self._http.post(self.base_url + path, json=body)
                if r.status_code == 200:
                    return r.json()
                text = r.text[:300].lower()
                retryable = (r.status_code in (408, 429, 500, 502, 503, 504)
                             or any(m in text for m in _LIMIT_MARKERS))
                if not retryable:
                    raise GatewayError(f"{path} -> HTTP {r.status_code}: {r.text[:300]}")
                last = GatewayError(f"HTTP {r.status_code}: {r.text[:200]}")
            except httpx.TransportError as e:
                # By type, not by string. CLAUDE.md records the same fix in gemma.py:
                # socket-layer drops phrase themselves too many ways ("_ssl.c:2580") for
                # a marker list to keep up.
                last = e
            except GatewayError:
                raise
            except Exception as e:  # noqa: BLE001 - classified, then re-raised below
                if not any(m in str(e).lower() for m in _TRANSIENT_MARKERS):
                    raise
                last = e
            if attempt < self.max_retries - 1:
                # A RATE-LIMIT REJECTION NEEDS A WINDOW-LENGTH WAIT, NOT 2 SECONDS. The old
                # ladder (2/4/8 = 14s) could never outlast a ~60s quota window, so a
                # corpus-sized job failed instead of slowing down. Rate limits now escalate
                # toward a full window and PENALISE THE SHARED BUCKET so sibling threads stop
                # too; genuine transport blips keep the short ladder.
                text_l = str(last).lower()
                is_parallel = any(m in text_l for m in _PARALLEL_MARKERS)
                is_limit = (any(m in text_l for m in _LIMIT_MARKERS)
                            or "429" in str(last)) and not is_parallel
                if is_parallel:
                    # A CONCURRENCY rejection, not a quota one, and it must NOT take the
                    # quota ladder. It clears as soon as a sibling request completes, so the
                    # wait is short -- and JITTERED, because the failure mode here is threads
                    # colliding: releasing them all on the same schedule just reproduces the
                    # collision. Deliberately does NOT penalise the shared bucket; slowing the
                    # whole job down does not create a free parallel slot.
                    wait = min(8.0, 1.0 * (attempt + 1)) * (1.0 + 0.5 * _jitter())
                    kind = "max_parallel"
                elif is_limit:
                    wait = min(75.0, 15.0 * (attempt + 1))
                    _embed_limiter.penalise(wait)
                    kind = "rate limit"
                else:
                    wait = 2 ** (attempt + 1)
                    kind = "transient"
                print(f"[gateway] {kind} on {path} "
                      f"(attempt {attempt + 1}); waiting {wait:.1f}s -- {str(last)[:100]}")
                time.sleep(wait)
        raise GatewayError(f"{path} failed after {self.max_retries} attempts: {last}")

    def list_models(self) -> list[dict]:
        """GET /models. Also the base-url sanity check: a base_url carrying a `/v1`
        segment does not 404 here, it connect-times-out (docstring note 1)."""
        r = self._http.get(self.base_url + "/models")
        if r.status_code != 200:
            raise GatewayError(f"/models -> HTTP {r.status_code}: {r.text[:200]}")
        return r.json().get("data", [])

    # -- chat --------------------------------------------------------------------

    def chat_json(self, prompt: str, *, model: str = CHAT_MODEL,
                  temperature: float = 0.2, max_tokens: int = 8192,
                  system: str | None = None, no_cache: bool = False,
                  reasoning_effort: str | None = None,
                  schema: dict | None = None) -> tuple[dict, dict]:
        """A JSON-forced completion. Returns (parsed, usage).

        Mirrors call_gemma's contract -- forced JSON, parsed with json.loads -- so a
        future swap is a transport change rather than a prompt change. Usage is
        returned rather than stashed in a module global because there is no reason to
        repeat gemma.py's LAST_MODEL_USED pattern in new code; it exists there only
        because that function's return value is the parsed dict itself.

        *** THE GATEWAY CACHES CHAT COMPLETIONS BY DEFAULT. Measured 2026-08-16: the same
        prompt returned BYTE-IDENTICAL free text in 1741ms, then 249ms, then 236ms, while a
        prompt differing by ONE trailing space returned different text in 806ms. ***

        That is invisible and it silently destroys any measurement whose design is "run the
        same thing twice and see how much the answer moves". It already did: a 245-cluster
        adjudication re-run as a noise floor came back 245/245 identical -- verdicts, keys,
        reasons and descriptions -- which reads as perfect determinism and is actually a
        cache echo of the first run.

        `no_cache=True` sends LiteLLM's `cache: {"no-cache": true}`, verified to bypass it
        (946ms/794ms, genuinely different text each call). ANY harness measuring run-to-run
        variance MUST set it. Left default-False so existing callers are unchanged: for a
        one-shot production pass the cache is a saving, not a hazard.

        `schema` (2026-09-08) upgrades the request from JSON MODE to a SCHEMA-CONSTRAINED
        response: pass a JSON Schema and the gateway restricts keys and enum values rather
        than merely guaranteeing parseable JSON. Measured on gemini-3.6-flash, two runs per
        arm with a negative control (ADR 0007): a schema declaring one property returned
        exactly that property against a prompt demanding four, while the same prompt without
        a schema returned all four; an `enum` held against a prompt demanding a value outside
        it.

        Default None keeps every existing caller's request body BYTE-IDENTICAL, which is not
        housekeeping -- Ask Naren's answering prompts are frozen against a measured accuracy
        number (ADR 0001) and a changed request body could move what the model returns. Do
        not attach a schema to them.

        Enforcement is a property of a gateway DEPLOYMENT and can change underneath us, so a
        caller passing a schema must still validate what comes back. A silent regression here
        would otherwise surface as a wrong value rather than an error.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": (
                {"type": "json_schema", "json_schema": schema} if schema
                else {"type": "json_object"}
            ),
        }
        if no_cache:
            body["cache"] = {"no-cache": True}
        # Optional, additive (2026-08-18, PV model amendment): LiteLLM forwards
        # `reasoning_effort` to reasoning-capable Gemini models. Default None keeps
        # every existing caller's request body byte-identical.
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        data = self._post("/chat/completions", body)
        content = (data["choices"][0]["message"].get("content") or "").strip()
        if not content:
            raise GatewayError(f"empty completion from {model}")
        try:
            # `served_model` rides along in the meta dict because the response reports
            # which model ACTUALLY answered, and callers were discarding it -- leaving
            # gateway provenance as "what we asked for" while the AI Studio path records
            # "what replied after fallback". Added to the existing dict rather than as a
            # third return value so none of the five callers change.
            meta = dict(data.get("usage") or {})
            meta["served_model"] = data.get("model")
            return json.loads(content), meta
        except json.JSONDecodeError as e:
            raise GatewayError(f"non-JSON from {model}: {e}\nRaw: {content[:400]}") from e

    # -- embeddings --------------------------------------------------------------

    def embed_one(self, text: str, *, model: str = EMBED_MODEL,
                  dimensions: int = EMBED_DIMENSIONS) -> list[float]:
        """One text, one request, one vector -- and it ASSERTS that.

        The assert is the entire point. See note 2 in the module docstring: this
        endpoint answers 200 with fewer vectors than inputs for some content, so the
        count is the only thing standing between a silent collapse and mis-attributed
        embeddings.
        """
        # TWO independent limits, both per API key, and BOTH must be respected:
        #   _embed_limiter   how OFTEN a request may start   (150 requests / window)
        #   _embed_parallel  how many may be IN FLIGHT       (max_parallel_requests = 8)
        # The bucket alone is not enough -- it happily starts 8 requests inside one interval
        # and leaves them all outstanding. Holding the semaphore across the ENTIRE _post,
        # retries included, is what makes the in-flight count real: releasing it before a
        # retry would let a ninth request start while this one is still logically alive.
        _embed_limiter.acquire()
        with _embed_parallel:
            data = self._post("/embeddings", {
                "model": model, "input": [text], "dimensions": dimensions,
            })
        got = data.get("data") or []
        if len(got) != 1:
            raise GatewayError(
                f"expected 1 embedding for 1 text, got {len(got)} -- "
                f"the endpoint collapsed the input (see module docstring note 2)"
            )
        vec = got[0]["embedding"]
        if len(vec) != dimensions:
            raise GatewayError(f"asked for {dimensions} dims, got {len(vec)}")
        return vec

    def embed(self, texts: list[str], *, model: str = EMBED_MODEL,
              dimensions: int = EMBED_DIMENSIONS, workers: int = 1,
              progress_every: int = 50) -> list[list[float]]:
        """Embed each text with its own request. Order is preserved.

        `workers > 1` fans the requests out across threads. That is a THROUGHPUT knob
        only -- each request still carries exactly one text, so it cannot reintroduce
        the collapse. httpx.Client is thread-safe for concurrent requests.
        """
        if not texts:
            return []
        out: list[list[float] | None] = [None] * len(texts)

        def work(i: int) -> None:
            out[i] = self.embed_one(texts[i], model=model, dimensions=dimensions)

        if workers <= 1:
            for i in range(len(texts)):
                work(i)
                if progress_every and (i + 1) % progress_every == 0:
                    print(f"[gateway] embedded {i + 1}/{len(texts)}", flush=True)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(work, range(len(texts))))

        if any(v is None for v in out):
            raise GatewayError("internal: some embeddings were never filled in")
        return out  # type: ignore[return-value]

    def embed_batched(self, texts: list[str], *, model: str = EMBED_MODEL,
                      dimensions: int = EMBED_DIMENSIONS) -> tuple[list[list[float]], bool]:
        """One request for the whole list, VERIFIED. Returns (vectors, batch_worked).

        Kept to demonstrate and detect the hazard, not as the recommended path. When the
        endpoint collapses the list this falls back to per-text so the caller still gets
        correct vectors, and reports False so the caller knows batching is unavailable
        for this content. Never trust the returned list positionally without this check.
        """
        if not texts:
            return [], True
        data = self._post("/embeddings", {
            "model": model, "input": texts, "dimensions": dimensions,
        })
        got = data.get("data") or []
        if len(got) != len(texts):
            return self.embed(texts, model=model, dimensions=dimensions,
                              progress_every=0), False
        # `index` is authoritative for ordering; do not assume the array is already sorted.
        ordered = sorted(got, key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in ordered], True



# =========================================================================================
# THE ASYNC TRANSPORT (added 2026-09-10, issue #28)
# =========================================================================================
#
# Everything above this line is the SYNCHRONOUS client and is unchanged. It is what Brain's
# pipeline uses, and a batch job that embeds a corpus behind a ThreadPoolExecutor is exactly
# what it is built for. Nothing below is imported by the pipeline.
#
# Everything below is its async twin, for Ask Naren's service, where a BLOCKING sleep would
# freeze every other CSM's in-flight request in the process. Same endpoints, same measured
# limits, same retry classification -- one execution model instead of two.
#
# *** THE TWO CLIENTS MUST NEVER RUN IN ONE PROCESS. *** Both limits the gateway enforces
# are PER API KEY, and each client keeps its own limiter. Two limiters cannot honour one
# budget: they would simply race each other into the same rejection, which is the exact
# failure the sync limiter's own docstring describes for two clients that do not share a
# bucket. The service uses the async client only; the pipeline uses the sync client only.
#
# *** THE ONE BEHAVIOURAL DIFFERENCE FROM THE SYNC CLIENT, AND IT IS A FIX. *** Admission
# control here wraps `_post`, so it covers CHAT AND EMBEDDINGS ALIKE. Above, the semaphore
# guards `embed_one` only -- the names `_embed_parallel` / `_embed_limiter` record that the
# cap was discovered during a corpus fetch. MEASURED 2026-09-10 against the production
# gateway with a direct async client: `max_parallel_requests` is 8 and the budget is SHARED.
# Six chat plus six embed fired together = 12 in flight -> 9 ok, 3 rejected. So generation
# counts against the same 8, and the sync client does not pace it at all. That is invisible
# while the service answers one CSM at a time, and is the first thing to break when it stops.
#
# Also measured in the same run: the gateway negotiates HTTP/2, and keep-alive works
# (1.45s then 0.88s through one client). So concurrent calls can multiplex over ONE socket,
# which is why `http2` defaults on here while the sync client leaves it off -- a batch job
# with one request per thread gains nothing from multiplexing.

#: Awaited for every wait in this module, and named so a test can replace it. A test that
#: patches this and then sees NO recorded waits has caught an implementation that blocked
#: the event loop instead of yielding it -- which is the defect this module exists to avoid
#: and is otherwise invisible.
_asleep = asyncio.sleep

# 6 against the measured ceiling of 8, and the two spare slots are not slack: a retry is
# itself a request, so operating ON the ceiling leaves a rejection nowhere to go. Same env
# override as the sync client's EMBED_MAX_PARALLEL, kept under its own name because this one
# bounds BOTH endpoints.
GATEWAY_MAX_PARALLEL = int(os.environ.get("BRAIN_GATEWAY_MAX_PARALLEL", "6"))

#: Jitter for colliding siblings, from a PRIVATE generator. The sync `_jitter` derives its
#: spread from `threading.get_ident()`, which is a single constant under one event loop --
#: every sibling would then back off in lockstep and reproduce exactly the collision the
#: jitter exists to break up. A dedicated Random also keeps this off module-level RNG state
#: that a calibration harness may have seeded for reproducibility, which is the reason the
#: sync jitter avoided `random` in the first place.
_jitter_rng = random.Random(0xA5)


class _AsyncRateLimiter:
    """The token bucket, asyncio-shaped. Same pacing arithmetic as `_RateLimiter`.

    *** THE LOCK IS GONE, AND THAT IS NOT AN OVERSIGHT. *** The sync limiter holds a mutex
    across the read-then-write of `_next` because another THREAD can be scheduled in the
    middle of it. Under one event loop nothing can interrupt a coroutine between two
    statements unless it awaits, and this one does not await until after the write. A lock
    here would guard against a thing that can no longer happen, and an `asyncio.Lock` would
    be one more object to hold correctly for no benefit.
    """

    def __init__(self, per_minute: int) -> None:
        self._min_interval = 60.0 / max(1, per_minute)
        self._next = 0.0

    async def acquire(self) -> None:
        now = time.monotonic()
        wait = self._next - now
        if wait <= 0:
            self._next = now + self._min_interval
            wait = 0.0
        else:
            self._next += self._min_interval
        if wait > 0:
            await _asleep(wait)

    def penalise(self, seconds: float) -> None:
        """Push the whole bucket back after a quota rejection, so EVERY sibling waits.

        Not a coroutine: it only assigns a float, and making it awaitable would add a
        suspension point in the middle of the retry ladder for no reason.
        """
        self._next = max(self._next, time.monotonic() + seconds)


#: One bucket and one semaphore PER EVENT LOOP.
#:
#: The limits are per API key, so every client in the process must draw from the same pair --
#: module level, exactly as the sync client's are, and for the same reason.
#:
#: Keyed on the running loop rather than kept as two bare module globals because an asyncio
#: primitive binds itself to the first loop that awaits on it and RAISES if it is later
#: awaited from another. A service has exactly one loop for its entire life, so this is a
#: single pair in production; a test session has one loop per test, and without this keying
#: the second test to touch the semaphore would fail with "bound to a different event loop".
#:
#: *** THE PRECONDITION THIS CREATES, AND IT IS LOAD-BEARING: THE CLIENT MUST BE DRIVEN BY
#: ONE LONG-LIVED LOOP. *** A caller that wrapped each request in its own `asyncio.run`
#: would get a FRESH limiter and semaphore every time, so admission control would silently
#: degrade from per-key to per-request -- i.e. unbounded, which is the exact failure this
#: whole module exists to prevent, and it would look perfectly healthy until the gateway
#: started rejecting. `ops/serve_ask_naren.py` must open one loop and keep it.
#:
#: Weak keys are for hygiene, NOT a collection guarantee: measured on 3.11.9, a semaphore
#: that has actually had to WAIT stores the loop it bound to, so the entry's value strongly
#: references its own weak key and that entry is never collected. Harmless where the
#: precondition above holds -- one loop, one pair, for the life of the process.
_async_gates: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _async_gate() -> "tuple[_AsyncRateLimiter, asyncio.Semaphore]":
    """`(embedding rate bucket, shared in-flight semaphore)` for the running loop."""
    loop = asyncio.get_running_loop()
    gate = _async_gates.get(loop)
    if gate is None:
        gate = (_AsyncRateLimiter(EMBED_PER_MINUTE),
                asyncio.Semaphore(GATEWAY_MAX_PARALLEL))
        _async_gates[loop] = gate
    return gate


class AsyncGatewayClient:
    """The async twin of `GatewayClient`. Same contract, awaited.

    `transport` exists for tests: it takes an `httpx.AsyncBaseTransport`, which is how the
    admission behaviour is observed without a network. Production passes nothing.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 timeout: float = 120.0, max_retries: int = 4, http2: bool = True,
                 transport: "httpx.AsyncBaseTransport | None" = None):
        base_url = base_url or os.environ.get("LLM_GATEWAY_URL", "")
        api_key = api_key or os.environ.get("LLM_GATEWAY_KEY", "")
        if not base_url or not api_key:
            raise GatewayError(
                "Set LLM_GATEWAY_URL and LLM_GATEWAY_KEY in Brain/.env "
                "(this file keeps no credentials in source -- it is tracked, .env is not)."
            )
        # Trailing '/' or a '/v1' someone helpfully added both break this gateway, and the
        # '/v1' case does not 404 -- it connect-times-out, so the symptom is a 20-second
        # hang rather than an error. Same normalisation as the sync client.
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.max_retries = max_retries
        self.http2 = http2
        kwargs: dict = {
            "timeout": timeout,
            "headers": {"Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"},
            # The pool must never be narrower than the semaphore, or httpx would queue
            # requests the gateway would have accepted and the real bound would silently
            # become httpx's default rather than the measured one.
            "limits": httpx.Limits(max_connections=max(2 * GATEWAY_MAX_PARALLEL, 16),
                                   max_keepalive_connections=max(GATEWAY_MAX_PARALLEL, 8)),
        }
        if transport is not None:
            kwargs["transport"] = transport
        else:
            kwargs["http2"] = http2
        self._http = httpx.AsyncClient(**kwargs)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncGatewayClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # -- transport ---------------------------------------------------------------

    async def _post(self, path: str, body: dict) -> dict:
        """POST with the sync client's retry split, and THE shared admission limit.

        *** THE SLOT IS TAKEN PER ATTEMPT AND RELEASED WHILE BACKING OFF. *** This is the
        one place the async client deliberately does NOT copy the sync client's structure,
        and the first version of this method did copy it -- wrongly.

        The sync client acquires its semaphore in `embed_one`, OUTSIDE `_post`, so the slot
        is necessarily held across the whole retry ladder. Its docstring justifies that as
        keeping our in-flight count equal to the gateway's. But the thing the gateway
        actually counts is requests IN FLIGHT, and a request sleeping out a backoff is not
        one -- so re-acquiring per attempt honours the real constraint just as strictly:
        never more than the bound are outstanding at any instant, because nothing can make
        a request without a slot.

        Holding across the ladder is not merely unnecessary here, it is harmful in a way it
        cannot be in the sync client. A quota rejection escalates to 15/30/45s AND
        `penalise` deliberately synchronises every sibling into that wait, so all six slots
        enter the ladder together. Chat does not take the rate bucket (it is not subject to
        the per-window limit) but it does need a slot -- so a purely EMBEDDING quota event
        would stall every CSM's generation for up to ~90s. That is precisely the freeze
        this module's header says it exists to prevent, and the sync client cannot exhibit
        it because its semaphore never covers chat at all.

        The cost of releasing is that a retry queues again behind waiting siblings. That is
        the fair outcome and it is bounded; a starved retry is better than a starved
        endpoint.
        """
        limiter, parallel = _async_gate()
        last: "Exception | None" = None
        for attempt in range(self.max_retries):
            try:
                # The slot covers the request and nothing else. `async with` returns it on
                # every path out, exceptions included.
                async with parallel:
                    r = await self._http.post(self.base_url + path, json=body)
                # Safe to read outside the slot: a non-streaming httpx response is already
                # fully read by the time `post` returns, so nothing here touches the socket.
                if r.status_code == 200:
                    return r.json()
                text = r.text[:300].lower()
                retryable = (r.status_code in (408, 429, 500, 502, 503, 504)
                             or any(m in text for m in _LIMIT_MARKERS))
                if not retryable:
                    raise GatewayError(
                        f"{path} -> HTTP {r.status_code}: {r.text[:300]}")
                last = GatewayError(f"HTTP {r.status_code}: {r.text[:200]}")
            except httpx.TransportError as e:
                # By type, not by string. CLAUDE.md records the same fix in gemma.py:
                # socket-layer drops phrase themselves too many ways ("_ssl.c:2580")
                # for a marker list to keep up.
                last = e
            except GatewayError:
                raise
            except Exception as e:  # noqa: BLE001 - classified, then re-raised below
                if not any(m in str(e).lower() for m in _TRANSIENT_MARKERS):
                    raise
                last = e
            if attempt < self.max_retries - 1:
                await _asleep(self._backoff(str(last), attempt, limiter, path))
        raise GatewayError(f"{path} failed after {self.max_retries} attempts: {last}")

    def _backoff(self, message: str, attempt: int, limiter: _AsyncRateLimiter,
                 path: str) -> float:
        """How long to wait, and what to tell the shared bucket. Same three-way split the
        sync client makes, because the three failures want genuinely different waits."""
        text_l = message.lower()
        is_parallel = any(m in text_l for m in _PARALLEL_MARKERS)
        is_limit = (any(m in text_l for m in _LIMIT_MARKERS)
                    or "429" in message) and not is_parallel
        if is_parallel:
            # A CONCURRENCY rejection clears the moment a sibling request completes, so the
            # wait is short -- and jittered, because the failure mode here IS siblings
            # colliding, and releasing them on one schedule reproduces it. Deliberately does
            # NOT penalise the bucket: slowing the key down creates no parallel slot.
            wait = min(8.0, 1.0 * (attempt + 1)) * (1.0 + 0.5 * _jitter_rng.random())
            kind = "max_parallel"
        elif is_limit:
            # A quota rejection needs a WINDOW-length wait; the old 2/4/8 ladder could never
            # outlast a ~60s window. Penalising the bucket stops every sibling too, because
            # the limit is per key and they are about to be rejected as well.
            wait = min(75.0, 15.0 * (attempt + 1))
            limiter.penalise(wait)
            kind = "rate limit"
        else:
            wait = 2 ** (attempt + 1)
            kind = "transient"
        print(f"[gateway] {kind} on {path} (attempt {attempt + 1}); "
              f"waiting {wait:.1f}s -- {message[:100]}")
        return wait

    async def list_models(self) -> list[dict]:
        """GET /models. Also the base-url sanity check, and the cheapest preflight there is
        for "can this process reach the gateway at all"."""
        r = await self._http.get(self.base_url + "/models")
        if r.status_code != 200:
            raise GatewayError(f"/models -> HTTP {r.status_code}: {r.text[:200]}")
        return r.json().get("data", [])

    # -- chat --------------------------------------------------------------------

    async def chat_json(self, prompt: str, *, model: str = CHAT_MODEL,
                        temperature: float = 0.2, max_tokens: int = 8192,
                        system: "str | None" = None, no_cache: bool = False,
                        reasoning_effort: "str | None" = None,
                        schema: "dict | None" = None) -> "tuple[dict, dict]":
        """A JSON-forced completion. Returns (parsed, usage).

        The request body is assembled IDENTICALLY to the sync client's, down to which keys
        are omitted when their argument is left at its default. That is not tidiness: Ask
        Naren's answering prompts are frozen against a measured accuracy number (ADR 0001),
        so a body differing by one key could move what the model returns and quietly
        invalidate that measurement.

        The gateway CACHES completions by default, so any harness measuring run-to-run
        variance must pass `no_cache=True`; for a one-shot production answer the cache is a
        saving rather than a hazard.

        Chat is NOT paced by the embedding rate bucket -- that 150-per-window ceiling was
        measured on gemini-embedding-2 and completions are not subject to it. The limit chat
        DOES share is the in-flight one, enforced in `_post`.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": (
                {"type": "json_schema", "json_schema": schema} if schema
                else {"type": "json_object"}
            ),
        }
        if no_cache:
            body["cache"] = {"no-cache": True}
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        data = await self._post("/chat/completions", body)
        content = (data["choices"][0]["message"].get("content") or "").strip()
        if not content:
            raise GatewayError(f"empty completion from {model}")
        try:
            meta = dict(data.get("usage") or {})
            meta["served_model"] = data.get("model")
            return json.loads(content), meta
        except json.JSONDecodeError as e:
            raise GatewayError(f"non-JSON from {model}: {e}\nRaw: {content[:400]}") from e

    # -- embeddings --------------------------------------------------------------

    async def embed_one(self, text: str, *, model: str = EMBED_MODEL,
                        dimensions: int = EMBED_DIMENSIONS) -> "list[float]":
        """One text, one request, one vector -- and it ASSERTS that.

        The assert is the entire point: this endpoint answers 200 with fewer vectors than
        inputs for some content, intermittently, so the count is the only thing standing
        between a silent collapse and mis-attributed embeddings (module docstring note 2).

        TWO limits apply and both must be respected. The per-window bucket governs how OFTEN
        a request may start and is embedding-specific; the in-flight semaphore inside `_post`
        governs how many may be outstanding at once and is shared with chat.
        """
        limiter, _ = _async_gate()
        await limiter.acquire()
        data = await self._post("/embeddings", {
            "model": model, "input": [text], "dimensions": dimensions,
        })
        got = data.get("data") or []
        if len(got) != 1:
            raise GatewayError(
                f"expected 1 embedding for 1 text, got {len(got)} -- "
                f"the endpoint collapsed the input (see module docstring note 2)"
            )
        vec = got[0]["embedding"]
        if len(vec) != dimensions:
            raise GatewayError(f"asked for {dimensions} dims, got {len(vec)}")
        return vec

    async def embed(self, texts: "list[str]", *, model: str = EMBED_MODEL,
                    dimensions: int = EMBED_DIMENSIONS) -> "list[list[float]]":
        """Embed each text with its own request, concurrently. Order is preserved.

        There is no `workers` argument, and its absence is the point: the sync version needs
        one because a thread pool has to be sized, while here the in-flight semaphore is
        already the bound and a second knob could only contradict it. Every request still
        carries exactly one text, so concurrency cannot reintroduce the collapse.

        Results are placed BY INDEX rather than appended, because these complete out of
        order and a caller reading them positionally would otherwise get vectors attributed
        to the wrong text -- the same hazard `embed_batched` exists to detect.
        """
        if not texts:
            return []
        out: "list[list[float] | None]" = [None] * len(texts)

        async def work(i: int) -> None:
            out[i] = await self.embed_one(texts[i], model=model, dimensions=dimensions)

        await asyncio.gather(*(work(i) for i in range(len(texts))))
        if any(v is None for v in out):
            raise GatewayError("internal: some embeddings were never filled in")
        return out  # type: ignore[return-value]
