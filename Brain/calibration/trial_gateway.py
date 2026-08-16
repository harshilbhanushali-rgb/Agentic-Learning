"""Standalone trial of the Joveo LLM gateway as a backend for BOTH Gemini surfaces.

NOTHING IN PRODUCTION IMPORTS THIS. It is a measurement harness, exactly like every
other script in calibration/ -- `shared/gemma.py` and `preprocessing/embedder.py` are
untouched and still talk to Google AI Studio directly. The point of this file is to
establish what the gateway actually does before anything is wired to it.

Run from Brain/:

    ../.venv/Scripts/python.exe calibration/trial_gateway.py            # full self-test
    ../.venv/Scripts/python.exe calibration/trial_gateway.py --quick    # skip the slow checks

Credentials come from Brain/.env (gitignored) as LLM_GATEWAY_URL / LLM_GATEWAY_KEY.
They are deliberately NOT defaulted in source: this file is tracked, .env is not.

================================================================================
MEASURED AGAINST THE LIVE GATEWAY 2026-08-15. None of this is assumed.
================================================================================

1. THE BASE URL HAS NO `/v1` PREFIX. `GET /models` works; `GET /v1/models` does not
   404 -- it CONNECT-TIMES-OUT after ~20s, which reads like a network fault rather
   than a wrong path and cost the first probe of this session. The OpenAI SDK appends
   `/chat/completions` to whatever base_url it is given, so base_url must be the bare
   host with no version segment.

2. *** /embeddings SILENTLY RETURNS FEWER VECTORS THAN INPUTS, INTERMITTENTLY. ***

   This is the single most important finding here and the reason `embed()` below
   sends ONE text per request.

   Measured, each reproduced 5-6 consecutive times within a single process:

     ["The client asked question number {i} regarding their recruitment
       advertising strategy and budget." for i in range(8)]        -> 8 vectors  OK
     ["alpha{i} " + "token "*20 for i in range(8)]                 -> 1 vector   COLLAPSE
     ["hello world", "the client asked about budget", "goodbye"]   -> 1 vector   COLLAPSE
     ["thank you", "goodbye now", "see you later"]                 -> 1 vector   COLLAPSE

   That first looked content-dependent and deterministic -- natural prose batches,
   short or repetitive text collapses -- because every set reproduced perfectly on
   repeat. IT IS NOT. Minutes later, in a fresh process, the identical
   ["thank you", "goodbye now", "see you later"] request returned 3 vectors
   correctly. Same key, same body, same `dimensions`.

   So the real rule is worse than a content rule: THE SAME REQUEST BATCHES OR
   COLLAPSES DEPENDING ON WHEN YOU SEND IT -- plausibly which upstream instance the
   gateway routes to. It is stable enough within a burst to look deterministic, which
   is exactly what makes it a trap: a batching implementation can be "verified"
   against a hundred consecutive successful calls and still lose data tomorrow.

   The `dimensions` parameter is not involved: holding text constant and varying it
   across {none,256,768,1536,3072} changes nothing.

   Why this is dangerous rather than merely annoying: the collapse is SILENT. HTTP
   200, well-formed body, no warning. A caller that zips inputs against `data` gets
   a shorter list and, if it does not check, silently mis-attributes every vector.
   CLAUDE.md already records this exact failure against the native SDK -- 161
   scenarios produced 2 vectors and surfaced as an IndexError far downstream only
   because a boolean mask happened to check a length. Same bug, new transport.

   And it lands precisely on THIS corpus. Layer A embeds 74k short client clauses and
   Layer D embeds turns like "Thank you." / "Yeah. That makes sense." -- the short end
   is not an edge case here, it is the bulk of the data. So batching is not "risky but
   faster", it is wrong for the population this pipeline actually embeds.

   `embed()` therefore sends one text per request and asserts exactly one vector came
   back. `embed_batched()` exists only to demonstrate the hazard: it verifies the
   count and falls back to per-text on mismatch. Do not promote it without
   re-measuring against real corpus text.

   COST OF THAT DECISION, measured: ~0.42s per sequential request (8 in 3.4s), so a
   74k-clause backfill is ~8.7 hours single-threaded. `--concurrency` measures whether
   parallel requests are accepted, which is the only thing that makes a backfill
   practical. That is a throughput question, NOT a correctness one -- concurrency does
   not make batching safe.

3. Vectors are unit-norm at every width (||v|| = 1.000000), so cosine is a bare dot
   product, matching what everything downstream already assumes.

4. Matryoshka truncation is EXACT: cos(api_at_768, first_768_of_3072) = 1.000000.
   One full-width call yields every narrower width for free.

5. Embeddings are deterministic: the same text embedded twice gives cosine 1.000000.
   This is the property that would remove the UMAP/HDBSCAN run-to-run variance
   CLAUDE.md documents for local bge (241 -> 231 -> 226 clusters for one corpus).

6. `task_type` and `input_type` are ACCEPTED (HTTP 200) and INERT -- cosine 1.000000
   against a request that omits them. So the gateway gives no query/document
   asymmetry, consistent with the existing note in preprocessing/embedder.py that
   task_type is inert on gemini-embedding-2. Any design leaning on bge's
   embed_query/embed_document split loses the mechanism entirely on this backend
   rather than merely changing it.

7. Chat honours `response_format={"type":"json_object"}` and returns bare JSON with no
   ```json fence, so `call_gemma`'s json.loads contract carries over unchanged. `usage`
   is populated, which the native path never gave us.

NOT MEASURED, and load-bearing before any migration: every threshold in tuning.yaml
was calibrated against bge's cosine bands (trigger p10=0.496 p50=0.550 p90=0.613).
This backend's bands are different and unmeasured. Switching is a re-calibration, not
a config change.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Standard calibration bootstrap: works as `python calibration/trial_gateway.py`
# from Brain/ and as `from calibration import trial_gateway`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
                wait = 2 ** (attempt + 1)
                print(f"[gateway] transient on {path} (attempt {attempt + 1}); "
                      f"waiting {wait}s -- {str(last)[:120]}")
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
                  system: str | None = None, no_cache: bool = False) -> tuple[dict, dict]:
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
            "response_format": {"type": "json_object"},
        }
        if no_cache:
            body["cache"] = {"no-cache": True}
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


# -- helpers ---------------------------------------------------------------------

def cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return num / (na * nb + 1e-12)


class Report:
    """PASS/FAIL accumulator. Exits non-zero if anything failed, so this is usable as a
    smoke test in a script rather than something a human has to read carefully."""

    def __init__(self) -> None:
        self.rows: list[tuple[bool, str, str]] = []

    def check(self, ok: bool, name: str, detail: str = "") -> bool:
        self.rows.append((ok, name, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
        return ok

    def note(self, name: str, detail: str) -> None:
        print(f"  [info] {name} -- {detail}")

    def finish(self) -> int:
        failed = [r for r in self.rows if not r[0]]
        print("\n" + "=" * 78)
        print(f"{len(self.rows) - len(failed)}/{len(self.rows)} checks passed")
        for _, name, detail in failed:
            print(f"  FAILED: {name} -- {detail}")
        print("=" * 78)
        return 1 if failed else 0


# -- the trial -------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quick", action="store_true",
                    help="skip the concurrency throughput check")
    ap.add_argument("--concurrency", type=int, default=16,
                    help="workers for the throughput check (default 16)")
    args = ap.parse_args()

    rep = Report()
    with GatewayClient() as gw:
        print(f"\ngateway : {gw.base_url}")
        print(f"chat    : {CHAT_MODEL}")
        print(f"embed   : {EMBED_MODEL} @ {EMBED_DIMENSIONS}d\n")

        # -- 1. the models endpoint, which is also the base-url sanity check ------
        print("[1] model catalogue")
        models = {m.get("id") for m in gw.list_models()}
        rep.check(CHAT_MODEL in models, f"{CHAT_MODEL} is offered")
        rep.check(EMBED_MODEL in models, f"{EMBED_MODEL} is offered")

        # -- 2. chat ------------------------------------------------------------
        print("\n[2] gemini chat, JSON-forced")
        parsed, usage = gw.chat_json(
            'Return JSON exactly: {"ok": true, "answer": 42}',
            temperature=0.0)
        rep.check(parsed.get("ok") is True and parsed.get("answer") == 42,
                  "returns parseable JSON matching the requested shape", str(parsed))
        rep.check(bool(usage), "usage accounting is populated", str(usage))

        # A prompt shaped like this pipeline's real ones: a list-of-objects payload,
        # which is what every Layer A/C/D prompt actually asks for. A model that can
        # only do flat key/value would pass the check above and fail in production.
        parsed2, _ = gw.chat_json(
            "Classify each utterance as 'substantive' or 'filler'. "
            'Return JSON {"items":[{"text":..., "label":...}]} for: '
            '["Thank you.", "We are spending about 40k a month on job boards."]',
            temperature=0.0)
        items = parsed2.get("items", [])
        rep.check(len(items) == 2, "handles a nested list-of-objects response shape",
                  json.dumps(parsed2)[:160])

        # -- 3. embeddings, the properties everything downstream assumes ---------
        print("\n[3] gemini embedding properties")
        A = "The client is worried about their monthly advertising budget increasing."
        B = "Bananas are yellow and grow in tropical climates near the equator."
        va = gw.embed_one(A)
        vb = gw.embed_one(B)
        rep.check(len(va) == EMBED_DIMENSIONS, f"native width is {EMBED_DIMENSIONS}",
                  f"got {len(va)}")

        norm = math.sqrt(sum(x * x for x in va))
        rep.check(abs(norm - 1.0) < 1e-4, "vectors are unit-norm (cosine == dot product)",
                  f"||v|| = {norm:.6f}")

        again = gw.embed_one(A)
        rep.check(cosine(va, again) > 0.99999, "deterministic across calls",
                  f"cos = {cosine(va, again):.6f}")

        rep.check(cosine(va, vb) < 0.85, "unrelated texts are separated",
                  f"cos(budget, bananas) = {cosine(va, vb):.4f}")

        v768 = gw.embed_one(A, dimensions=768)
        rep.check(len(v768) == 768, "dimensions parameter is honoured")
        rep.check(cosine(v768, va[:768]) > 0.99999,
                  "Matryoshka truncation is exact (768 == first 768 of 3072)",
                  f"cos = {cosine(v768, va[:768]):.6f}")

        # -- 4. THE HAZARD ------------------------------------------------------
        # This is the check that justifies the whole design of embed(). It asserts the
        # collapse EXISTS rather than asserting it doesn't -- if the gateway is ever
        # fixed this check fails loudly, which is the correct way to find out.
        print("\n[4] batch-collapse hazard (the reason embed() sends one text per request)")
        # Deliberately NOT asserted either way. The collapse is intermittent (docstring
        # note 2), so "it collapsed" and "it didn't" are both valid observations and
        # neither is a pass condition. Asserting the bug reproduces was itself a bug:
        # the check went red the moment the gateway happened to answer correctly.
        # What IS asserted is the invariant that survives both outcomes -- the vectors
        # come back correct because the count is verified, never because it was trusted.
        short = ["thank you", "goodbye now", "see you later"]
        collapses = sum(0 if gw.embed_batched(short, dimensions=256)[1] else 1
                        for _ in range(5))
        rep.note("short-utterance batch collapse rate",
                 f"{collapses}/5 collapsed this run -- intermittent by design of the "
                 f"gateway, so batching is never safe regardless of what you observe")

        prose = [f"The client asked question number {i} regarding their recruitment "
                 f"advertising strategy and budget." for i in range(8)]
        vecs, prose_ok = gw.embed_batched(prose, dimensions=256)
        rep.note("natural-prose batch", f"batch_worked={prose_ok}")

        # Whatever path embed_batched took, the vectors must still be right. Verify
        # positionally against independently embedded references -- a count check alone
        # is what failed silently last time.
        ref0 = gw.embed_one(prose[0], dimensions=256)
        ref7 = gw.embed_one(prose[7], dimensions=256)
        rep.check(cosine(vecs[0], ref0) > 0.999 and cosine(vecs[7], ref7) > 0.999,
                  "embed_batched output is positionally correct either way",
                  f"cos[0]={cosine(vecs[0], ref0):.4f} cos[7]={cosine(vecs[7], ref7):.4f}")

        # The same positional guarantee on the collapse-prone content, which is the
        # case that actually matters for this corpus.
        sv, _ = gw.embed_batched(short, dimensions=256)
        s0, s2 = gw.embed_one(short[0], dimensions=256), gw.embed_one(short[2], dimensions=256)
        rep.check(len(sv) == 3 and cosine(sv[0], s0) > 0.999 and cosine(sv[2], s2) > 0.999,
                  "short-text batch output is positionally correct even when it collapsed",
                  f"cos[0]={cosine(sv[0], s0):.4f} cos[2]={cosine(sv[2], s2):.4f}")

        # The safe path, on exactly the content that breaks batching.
        safe = gw.embed(short, dimensions=256, progress_every=0)
        rep.check(len(safe) == 3 and all(len(v) == 256 for v in safe),
                  "embed() returns one correct vector per short text")

        # -- 5. throughput ------------------------------------------------------
        if not args.quick:
            print("\n[5] throughput (one request per text is the cost of correctness)")
            sample = [f"The client raised concern number {i} about campaign pacing "
                      f"and applicant quality this quarter." for i in range(24)]
            t0 = time.time()
            gw.embed(sample[:8], dimensions=256, progress_every=0)
            seq = time.time() - t0
            t0 = time.time()
            par = gw.embed(sample, dimensions=256, workers=args.concurrency)
            conc = time.time() - t0
            rep.check(len(par) == 24, f"{args.concurrency} concurrent workers all succeeded")
            per_seq = seq / 8
            per_conc = conc / 24
            rep.note("latency", f"sequential {per_seq:.2f}s/text, "
                                f"concurrent@{args.concurrency} {per_conc:.3f}s/text "
                                f"({per_seq / max(per_conc, 1e-6):.1f}x)")
            rep.note("74k-clause backfill estimate",
                     f"sequential {74000 * per_seq / 3600:.1f}h, "
                     f"concurrent {74000 * per_conc / 3600:.1f}h")

    return rep.finish()


if __name__ == "__main__":
    raise SystemExit(main())
