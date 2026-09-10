#!/usr/bin/env python3
"""How many requests will the gateway take at once, and is that budget shared? (issue #28)

Run from Brain/, with the Joveo VPN up:

    ../.venv/Scripts/python.exe ../ask-naren/audit/probe_gateway_concurrency.py

WHY THIS EXISTS AS A COMMITTED HARNESS. `shared/gateway.py` sizes its admission limit from
two measured numbers, and the whole concurrency ceiling of Ask Naren follows from them:

    150 requests / window   -- measured on /embeddings, gemini-embedding-2
    max_parallel_requests=8 -- SHARED across /chat/completions and /embeddings

The second one is what this probe established on 2026-09-10, and it is a property of the
KEY that the gateway team can change. When it changes, the semaphore's bound should change
with it -- so the measurement has to be repeatable rather than a number in a comment.

*** DELIBERATELY DOES NOT USE `GatewayClient` OR `AsyncGatewayClient`. *** Both retry and
classify 429s, which is exactly the behaviour that HIDES a rejection. This probe wants the
raw status of every attempt, so it talks to httpx directly. Use `check_async_transport.py`
to verify the client; use this to find the wall it should sit below.

RESULT ON 2026-09-10 (bound was set to 6 from this):
    1, 2, 4, 6, 8 concurrent chat -> all clean
    10 concurrent chat            -> 2 rejected, max_parallel_requests
    6 chat + 6 embed together     -> 9 ok, 3 rejected  (so the budget is SHARED)
    HTTP/2 negotiated; keep-alive works (1.45s then 0.88s through one client)

TWO TRAPS THIS HANDLES, both of which produced a wrong answer first time:

  * THE CHAT CACHE. The gateway caches completions by default -- the same prompt returned
    byte-identical text in 1741ms, then 249ms. Firing identical prompts concurrently
    measures the cache, not concurrency. Every call carries a unique nonce AND `no-cache`.
  * MARKER-SCANNING A SUCCESS BODY. An /embeddings 200 is 3072 floats, and "429" appears
    inside values like 0.0429 -- so scanning every body for rejection markers reported a
    perfectly good vector as a quota rejection. Markers are read on non-200 only.

Also refuses to infer a ceiling from a wave where NOTHING connected: with the VPN down,
every call fails and no request can be rejected for parallelism, which an earlier version
happily reported as "no parallel rejection up to 12".

COST: 43 chat calls at 64 tokens, plus 12 embeddings. Read-only -- /chat/completions,
/embeddings and /models are the only endpoints touched. The key is read from Brain/.env and
never printed.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "Brain" / ".env")

CHAT_MODEL = "gemini-3.5-flash-lite"
EMBED_MODEL = "gemini-embedding-2"
EMBED_DIMENSIONS = 3072

#: 8 is the measured ceiling, so 10 and 12 are what prove chat shares it.
CHAT_WAVES = (1, 2, 4, 6, 8, 10, 12)

#: Small, but not so small that a call finishes before its siblings have started -- a wave
#: that completed serially would report no rejections while proving nothing.
MAX_TOKENS = 64

#: Between waves, so one wave's outstanding requests are not counted against the next.
WAVE_GAP_S = 6.0

PARALLEL_MARKERS = ("max_parallel_requests", "max parallel")
LIMIT_MARKERS = ("429", "resource_exhausted", "quota", "rate limit")


def _base_url() -> str:
    url = os.environ.get("LLM_GATEWAY_URL", "")
    if not url or not os.environ.get("LLM_GATEWAY_KEY", ""):
        raise SystemExit("Set LLM_GATEWAY_URL and LLM_GATEWAY_KEY in Brain/.env")
    url = url.rstrip("/")
    # A base_url carrying a '/v1' segment does not 404 here, it connect-times-out.
    return url[:-3] if url.endswith("/v1") else url


def _headers() -> dict:
    return {"Authorization": "Bearer " + os.environ["LLM_GATEWAY_KEY"],
            "Content-Type": "application/json"}


class Outcome:
    """One request's raw result. No retry, no classification beyond reading a failure."""

    def __init__(self, kind: str, status: int, elapsed: float, body: str) -> None:
        self.kind = kind
        self.status = status
        self.elapsed = elapsed
        self.body = body
        low = body.lower()
        # Markers on a NON-200 only. See "MARKER-SCANNING A SUCCESS BODY" above.
        failed = status != 200
        self.parallel_reject = failed and any(m in low for m in PARALLEL_MARKERS)
        self.quota_reject = (failed and not self.parallel_reject
                             and (status == 429 or any(m in low for m in LIMIT_MARKERS)))

    @property
    def ok(self) -> bool:
        return self.status == 200

    def label(self) -> str:
        if self.ok:
            return "ok"
        if self.parallel_reject:
            return "MAX_PARALLEL"
        if self.quota_reject:
            return "quota/rate"
        return "HTTP " + str(self.status)


async def _chat(client: httpx.AsyncClient, base: str) -> Outcome:
    nonce = uuid.uuid4().hex[:8]
    prompt = ("Return a JSON object with one key 'n' whose value is the string "
              + nonce + ", and a key 'note' holding one short sentence.")
    body = {
        "model": CHAT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "cache": {"no-cache": True},
    }
    t0 = time.monotonic()
    try:
        r = await client.post(base + "/chat/completions", json=body)
        return Outcome("chat", r.status_code, time.monotonic() - t0, r.text[:300])
    except Exception as e:                 # noqa: BLE001 -- a transport failure IS a result
        return Outcome("chat", 0, time.monotonic() - t0, type(e).__name__ + ": " + str(e))


async def _embed(client: httpx.AsyncClient, base: str) -> Outcome:
    # ONE text per request. Never batch this endpoint.
    text = "probe " + uuid.uuid4().hex[:8] + " client situation about cost per hire"
    body = {"model": EMBED_MODEL, "dimensions": EMBED_DIMENSIONS, "input": [text]}
    t0 = time.monotonic()
    try:
        r = await client.post(base + "/embeddings", json=body)
        return Outcome("embed", r.status_code, time.monotonic() - t0, r.text[:300])
    except Exception as e:                 # noqa: BLE001
        return Outcome("embed", 0, time.monotonic() - t0, type(e).__name__ + ": " + str(e))


def _report(title: str, outs: list) -> None:
    if not outs:
        return
    lat = sorted(o.elapsed for o in outs)
    okc = sum(1 for o in outs if o.ok)
    par = sum(1 for o in outs if o.parallel_reject)
    quo = sum(1 for o in outs if o.quota_reject)
    print("  {:<26} ok {:>2}/{:<2}  max_parallel {:>2}  quota {:>2}  other {:>2}  "
          "min {:>5.2f}s  max {:>5.2f}s".format(
              title, okc, len(outs), par, quo, len(outs) - okc - par - quo,
              lat[0], lat[-1]))
    for o in outs:
        if not o.ok:
            print("      -> " + o.label() + ": " + o.body[:160])


async def wave_a(client: httpx.AsyncClient, base: str):
    """Chat concurrency. Returns the widest wave that took no parallel rejection."""
    print("\nWAVE A -- /chat/completions concurrency")
    print("  Does chat share the /embeddings max_parallel_requests budget?")
    clean = None
    for k in CHAT_WAVES:
        outs = list(await asyncio.gather(*(_chat(client, base) for _ in range(k))))
        _report(str(k) + " concurrent chat", outs)
        if any(o.parallel_reject for o in outs):
            print("  >> parallel ceiling reached between " + str(clean) + " and " + str(k))
            return clean
        if not any(o.ok for o in outs):
            raise SystemExit(
                "\n  ABORTED: not one request in the " + str(k) + "-wide wave succeeded.\n"
                "  A ceiling cannot be inferred from calls that never reached the gateway.\n"
                "  ConnectError on every call almost always means the Joveo VPN is down.")
        clean = k
        await asyncio.sleep(WAVE_GAP_S)
    print("  >> no parallel rejection up to " + str(clean) + " concurrent chat calls")
    return clean


async def wave_b(client: httpx.AsyncClient, base: str) -> None:
    """One budget or two? Ask Naren's request path interleaves both endpoints, so a shared
    budget means the semaphore must cover both -- which is what `_post` does."""
    print("\nWAVE B -- 6 chat + 6 embed together (shared budget or separate?)")
    outs = list(await asyncio.gather(
        *(_chat(client, base) for _ in range(6)),
        *(_embed(client, base) for _ in range(6))))
    _report("6 chat + 6 embed", outs)
    _report("  of which chat", [o for o in outs if o.kind == "chat"])
    _report("  of which embed", [o for o in outs if o.kind == "embed"])
    if any(o.parallel_reject for o in outs):
        print("  >> SHARED budget: 12 in flight across both endpoints was rejected.")
    else:
        print("  >> no rejection at 12 mixed in flight -- either the budget is "
              "per-endpoint, or it is larger than it was. Widen wave A before raising "
              "GATEWAY_MAX_PARALLEL.")


async def wave_c(base: str) -> None:
    """Transport facts that decide how the async client is built.

    "Does the gateway support async" is not a server property -- any HTTP endpoint can be
    called from asyncio. These two ARE server properties and both change the design:
    keep-alive (is one connection reused, or does every request pay a TLS handshake) and
    HTTP/2 (can concurrent requests multiplex over one socket).
    """
    print("\nWAVE C -- transport")
    async with httpx.AsyncClient(timeout=120.0, headers=_headers()) as c:
        first = await _chat(c, base)
        second = await _chat(c, base)
        print("  keep-alive: call1 {:.2f}s ({}), call2 {:.2f}s ({})".format(
            first.elapsed, first.label(), second.elapsed, second.label()))
        print("    a faster call2 means the TLS handshake was reused")
    try:
        async with httpx.AsyncClient(timeout=120.0, headers=_headers(), http2=True) as c:
            r = await c.get(base + "/models")
            print("  HTTP/2 on /models: " + str(r.http_version)
                  + " (HTTP " + str(r.status_code) + ")")
            print("    >> multiplexing available: N concurrent calls share ONE socket"
                  if r.http_version == "HTTP/2" else
                  "    >> HTTP/1.1 only; concurrency uses the connection pool, so keep "
                  "max_connections >= the semaphore")
    except Exception as e:                 # noqa: BLE001
        print("  HTTP/2 attempt failed: " + type(e).__name__ + ": " + str(e))


async def main() -> int:
    base = _base_url()
    print("gateway: " + base + "   (key loaded, not printed)")
    print("read-only: /chat/completions, /embeddings and /models only")

    # httpx defaults to 10 max_connections, which would silently cap a 12-wide wave and
    # look exactly like a gateway limit.
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=32)
    async with httpx.AsyncClient(timeout=120.0, headers=_headers(), limits=limits) as client:
        try:
            r = await client.get(base + "/models")
            print("preflight /models: HTTP " + str(r.status_code))
            if r.status_code != 200:
                raise SystemExit("preflight failed: " + r.text[:200])
        except httpx.TransportError as e:
            raise SystemExit(
                "preflight could not reach the gateway: " + type(e).__name__ + ": " + str(e)
                + "\n  Is the Joveo VPN up? Nothing was measured, no quota spent.") from None

        ceiling = await wave_a(client, base)
        await asyncio.sleep(WAVE_GAP_S)
        await wave_b(client, base)
    await wave_c(base)

    print("\nWHAT TO DO WITH THIS")
    print("  Set shared/gateway.GATEWAY_MAX_PARALLEL one or two below the widest clean "
          "wave, because a retry is itself a request. Wave A cleared: " + str(ceiling))
    print("  If wave B rejected, that bound must wrap _post (chat AND embed), not just "
          "embed_one -- which is what the sync client still does.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
