# PROTOTYPE — throwaway, do not build on this directly

Answers one question from `ask-naren/docs/adr/0001-layer-c-is-a-switch-not-a-default.md`:
**does adding a scenario's Layer C playbook (`key_moves`) to the prompt actually improve
Ask Naren's grounded answers, or not?**

This is not UI or state-machine work, so it isn't the usual HTML click-through prototype —
it's a runnable eval harness against the real Brain pipeline (Postgres, the live
`gateway`/`gemini-embedding-2` retrieval space, and `gemini-3.6-flash` generation).

Judging method deliberately avoids a holistic "which answer is better" LLM judge — that
exact shape already failed on this corpus (`Brain/docs/findings/head-to-head-comparison.md`:
position-swap agreement 0.669 vs a ≥0.75 bar, transplant-penalty 0.835 fatal false-positive).
Instead every check is programmatic/evidence-gated: does the answer cite the call it was
actually grounded in, does it contain a verbatim quote from that real response, and how close
is it (by embedding cosine, not by an LLM's opinion) to the real Naren response for that
situation. See the module docstring in `eval_pairs_vs_playbook.py` for the full method.

## Run it

From the repo root, with Brain's venv active:

```
.venv\Scripts\activate
python ask-naren\prototype\eval_pairs_vs_playbook.py --run
```

Costs ~2×N `gemini-3.6-flash` calls (N=25 by default → ~50 calls); embeddings are
free/near-free off the warm gateway cache. Re-print the same run without spending anything:

```
python ask-naren\prototype\eval_pairs_vs_playbook.py --load ask-naren\prototype\artifacts\eval_pairs_vs_playbook.json
```

## Test set

There is no independent ground-truth test set for Ask Naren yet (the closest existing
artifact, `Brain/artifacts/h2h_moments.json`, belongs to the now-closed head-to-head
experiment and isn't reused here on purpose). This script builds its own small held-out
sample: one real trigger/response pair per coachable scenario that has a live playbook,
sampled with a fixed seed from `kb_pairs`, filtered to reasonably substantive text. The full
text of every held-out item and what was retrieved for it prints in the report, so it can be
read and sanity-checked by a human rather than trusted blind.

## Capture

Once this has answered the question, fold the validated prompt/retrieval shape into the real
`ask-naren/` implementation and capture the verdict (which variant won, or "neither is good
enough yet") in a commit message or the next handoff — per the root `prototype` skill's
capture step. This directory and its `artifacts/` are throwaway; they are not meant to ship.
