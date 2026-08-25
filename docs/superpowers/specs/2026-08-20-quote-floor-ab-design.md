# Quote-floor A/B (PBQ) — design and FROZEN GATES (2026-08-20)

Operator directive: probe the new 3-quote floor, and A/B it against the scenarios already
done so the quality change is visible rather than assumed.

**Gates are pre-registered BEFORE the harness exists.** At any gate failure: STOP, report,
bring fallback options. Do not proceed to the 29-document backfill on a failed probe.

## 1. What is being tested

`MIN_EVIDENCE_PER_MOVE` was raised 2 → 3 and the diversity instruction hardened, because PB1
(≥3 distinct accounts per move) was **arithmetically unreachable** while the prompt permitted
2-quote moves — 89% of moves carried exactly 2 quotes and PB1 failed 0/11 documents before
quality was assessed. See `docs/findings/layer-c-playbook-schema-and-gateway.md` §9.

The change is a **hypothesis with zero model evidence behind it.** This spends ~15–25 chat
calls to test it on 5 documents before ~90 are spent on 29.

## 2. Arms

| arm | documents | prompt | cost |
| --- | --- | --- | --- |
| **OLD** | the 5 LIVE playbooks, as shipped | 2-4 entries, soft "Prefer … DISTINCT accounts" | **0** — they exist |
| **NEW** | same 5 scenarios, re-synthesized | 3-4 entries + hardened `_REQUIRE` | ~15–25 calls |

**Paired on evidence, and that part IS single-variable.** The NEW arm reuses the OLD arm's
selected 50 pairs verbatim from `artifacts/pbv_evidence.json` — same scenarios, same pairs,
same order. No re-selection, no embedding, no re-routing. G-Q5 asserts it rather than
assuming it.

**NOT single-variable on the prompt, and this is stated rather than hidden.** The OLD arm's
identity records `reduce_rules: "pilot_original_hardening_dropped_by_operator"`, so it ran the
SOFT wording. The NEW arm runs the 3-entry floor AND the hardened `_REQUIRE`. This is therefore
a **config-level** comparison — "old shipped config vs new shipped config" — which is the
question the operator actually asked ("is the new output better"), not an attribution of the
effect to one of the two changes. Attributing would need a third arm and ~15 more calls.

**Model confound, recorded.** `pbv_playbooks.json` identity says `gemini-3.5-flash-lite`, but
`playbook_validation.py` sets `PV_CHAT_MODEL = "gemini-3.5-flash"` with a note that 6 flash-lite
documents stand and later ones ran on flash. There is **no per-document model provenance**, so
the OLD arm may be mixed. NEW runs entirely on `gemini-3.5-flash-lite` (what the artifact
records). If a gate fails narrowly, this is a candidate explanation and must be named.

## 3. FROZEN GATES

| Gate | Statement | Fail action |
| --- | --- | --- |
| **G-Q1** | **The operator's probe bar: ≥70% of NEW-arm moves satisfy PB1 per-move** (≥3 distinct accounts, or ≥ accounts available). Baseline is 0%. | STOP. The floor change did not work. Do NOT start the 29-document backfill. |
| **G-Q2** | PB0 passes **5/5** in the NEW arm. Citation integrity must not regress. | STOP — the fix broke the shipping bar. |
| **G-Q3** | Every NEW document has 3–6 moves and **no `schema_collapsed`** after snap. | STOP. |
| **G-Q4** | **The floor actually took: ≥90% of NEW moves carry ≥3 quotes.** | STOP and report — the model ignored the instruction; that is the finding, and no downstream number means anything. |
| **G-Q5** | The NEW arm's evidence is byte-identical to the OLD arm's selected pairs. | ABORT before spending. |
| **G-Q6** | Hard stop at **25 chat attempts**. Every attempt counted, including invalid-JSON retries. | HALT and ask. |

**Descriptive comparisons (reported, NOT gates):** quotes per move, distinct accounts per move,
moves per document, share of single-account moves, PB1 span. These describe the quality change;
they do not decide it.

## 4. Safety

- Writes **only** to a NEW `pbq_*` artifact prefix. **No `pbv_*` file is touched** — those are
  published and are the source of the 5 live playbooks.
- **Nothing is loaded into Postgres by this harness.** The `playbooks` table is untouched;
  promoting anything is a separate, later, operator decision.
- Every chat call `no_cache=True` — the gateway caches completions and an echo would fake
  agreement between arms.
- Every attempt persisted BEFORE its result is used, so a crash cannot lose paid work.
- ONE blind code audit before it spends.

## 5. What a PASS licenses, and what it does not

A pass licenses starting the 29-document backfill at the new floor. It does **not** establish
that the new documents are *better coaching material* — PB1 is an evidence-breadth check, not a
quality judgement, and no human reads it. The blinded-read instrument remains the binding
constraint on quality claims (80% position bias, ~28% power), and nothing here changes that.

---

## 6. RESULTS (2026-08-20)

Four arms, same 5 scenarios, same frozen evidence (G-Q5 passed on all).

| arm | PB1 per-move | single-acct | usable quotes (blind read) |
| --- | --- | --- | --- |
| OLD shipped (flash-lite, 2-entry) | 10% | 15% | 63% |
| flash-lite low + 3-entry | 11% | 26% | 54% |
| 3.6-flash low + 3-entry | 58% | 5% | 79% |
| **3.6-flash MEDIUM + 3-entry** | **77%** (G-Q1 PASS) | 0% | 84% |
| 3.6-flash medium + relevance rule | 67% (FAIL) | 6% | **95%** |

**G-Q1 passed on the fourth arm and failed on the fifth — and the fifth is the better one.**
The relevance rule drove failing quotes to ZERO and usable to 95%, while dropping 4 moves it
could not evidence; PB1 fell because those moves were disproportionately PB1-passers. That is
the gate punishing the improvement, and it is why PB1 should be a diagnostic rather than a bar.

**`medium` reasoning failed entirely on `gemini-3.5-flash-lite`** (15s upstream timeout, 1 of 2
calls) and ran clean on `gemini-3.6-flash` at a 60.8s median. The limit is per-model, not
per-gateway — the note claiming otherwise was corrected the same day.

**The probe's 95% did not survive scale: 28 backfilled documents measured 73%.** See
`docs/findings/layer-c-playbook-schema-and-gateway.md` §11.3.
