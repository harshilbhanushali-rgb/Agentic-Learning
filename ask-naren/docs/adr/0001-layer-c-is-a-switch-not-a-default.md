# Ask Naren treats Layer C playbook context as an evaluated switch, not a default input

Ask Naren answers a CSM's situation by retrieving the closest matching `kb_pair` (Brain's Layer B) and paraphrasing Naren's real historical response. Brain's Layer C playbooks could additionally supply structured "ideal move sequence" context for that scenario — but Layer C's criterion quality is explicitly unresolved: two blind reads of the same 123 live criteria returned 84% and 17% gradable depending only on how the reader was framed, so no real gradability rate can currently be quoted (`Brain/CLAUDE.md`, "TWO KNOWN DEFECTS IN WHAT IS LIVE").

We decided to ship two parallel prompt variants — pairs-only and playbook-augmented — and let a blinded pairwise-judge eval against held-out real Naren answers (plus a human blind spot-check) decide which becomes the default, rather than assuming playbook context improves answers.

Adding unverified structure to a CSM-facing answer risks baking in confidently-wrong guidance under the appearance of more rigor. Treating "does playbook context help" as a measured question — the same discipline Brain already applies to Layer D's grader-arm choice — avoids that risk.

## Result (2026-08-26): default is pairs-only, playbook switch OFF

The eval method above was changed before running: a blinded pairwise judge is exactly the shape `Brain/docs/findings/head-to-head-comparison.md` already measured and closed on this same corpus (position-swap agreement 0.669 against a >=0.75 bar; a transplant-penalty control at 0.835 that would have produced a false headline). We built `ask-naren/prototype/eval_pairs_vs_playbook.py` instead: a held-out sample of real trigger/response pairs, real retrieval in the live gateway/gemini-embedding-2 space, real `gemini-3.6-flash` generation for both variants, scored with evidence-gated programmatic checks (does the answer cite the retrieved call, does it contain a verbatim quote, cosine similarity to the real ground-truth response) rather than an LLM judging quality.

Two corrected runs (24-25 held-out items, ~12-17 paired after excluding items either variant declined) found **no measurable lift from the playbook**: paired delta on similarity-to-ground-truth was -0.005 to -0.007, with a standard error the same size as the delta — indistinguishable from zero. Grounding discipline (citing the right call, quoting it verbatim) was already at or near 100% for both variants, so the playbook doesn't fix a grounding gap either. Full results: `ask-naren/prototype/artifacts/eval_pairs_vs_playbook_v2.json`.

**Decision: ship pairs-only as the default. The playbook-augmented variant stays off** — not removed, since Layer C's own quality is still evolving (see `Brain/CLAUDE.md`'s Layer C caveats) and a future recalibration could change this, but there is currently no evidence to justify its extra prompt cost and its dependency on Layer C's unresolved criterion-gradability rate.

Caveat carried forward: this is a prototype-scale sample (n=24-25, paired n=12-17), not a statistically powered study. It answers "is there an effect large enough to see here" (no), not "does an effect exist" (unknown). Revisit with a larger sample if the switch decision ever becomes load-bearing enough to need more confidence than that.
