# Layer D — Over 100 CSM Calls, Two Defects Exposed (2026-08-13)

[Findings index](INDEX.md)

### Layer D over 100 CSM calls, and two defects it exposed (2026-08-13)

Ran the EXISTING Layer D unchanged over 100 of the 107 CSM transcripts (7 excluded, see
below) instead of the ~19 used until now. One variable: input volume. Log
`logs/run_ego_trap_100calls.log`, 100/100 transcripts, zero tracebacks, ~70 min,
~230 flash-lite calls across both keys, embeddings local.

| | 19 calls | 100 calls |
| --- | --- | --- |
| attempts | 889 | **4,181** |
| milestones touched | 237 | **378** |
| per milestone (mean) | 3.75 | **11.1** |
| per milestone (MEDIAN) | — | **7.0** |
| weighted | 0.074-0.080 | **0.0785** |

- **Observations per milestone grow SUB-LINEARLY, and a projection that assumes otherwise
  is wrong.** 5.3x the calls gave 4.7x the attempts but only 2.9x the per-milestone mean,
  because more calls also drag previously-untouched milestones into play (237 -> 378). A
  pre-run estimate of "~20-30 per milestone" was made assuming a fixed denominator and the
  real median is **7**. **Reaching a median of 25 needs ~350+ calls, not the ~130 first
  quoted.** Any future "how many calls do we need" estimate must model the milestone count
  growing too.
- **A minority IS now well powered**: 26 milestones clear 23 attempts and 3 clear 83
  (the strictest standard). The distribution is 108 at 0-4, 155 at 5-11, 89 at 12-22.
  That is the population a partial vocabulary would report on — see the skills section.
- **The weighted score did not move** (0.0785 vs the 0.074-0.080 noise band), which is the
  correct outcome: same rubrics, same grader, so more data makes the number precise rather
  than different.

**DEFECT 1 — `Signal_Recognition_Failure` is 98.6% a segmentation artifact. MEASURED, free,
over all 100 transcripts.** `transcript_parser.turns_until_next_client` stops at the NEXT
CLIENT turn, so when a client speaks several turns in a row — a pause, a continued thought,
or the transcriber splitting one utterance — every turn but the last gets an **empty**
response window and `classify_response_outcome` returns `"none"` by construction. Of 5,731
client turns: 2,144 `csm` / 1,103 `other_joveo` / **2,484 `none`**. Of those 2,484,
**2,449 (98.6%) are immediately followed by ANOTHER CLIENT TURN**, 35 are the last turn of
the call, and **0 are genuine silence.** It does not measure whether the CSM responded; it
measures whether a client turn happened to be last in its block. **This retires the claim
recorded here that "36% of gap_events are `Signal_Recognition_Failure` — no CSM response
existed to score at all"**, which had been cited as a real cause of the low hit rate. Scored
milestones are UNAFFECTED (only `csm` outcomes are scored, and those are correct); what is
corrupted is the failure count and any coaching output derived from it. Fixing it means
treating consecutive client turns as ONE client move, which changes what counts as a signal
and therefore the denominator — pre-register it.

**DEFECT 2 — the GRADER never sees the client turn, the scenario, or the milestone label.**
Read from `ego_trap/milestone_scoring.py::score_milestones_batch`, the entire per-exchange
prompt is: Naren's benchmark response, the CSM response, and per milestone only
`description` + `detection_hint`. Not sent: the **client turn**, the **scenario_key**, and
the **`label`** — which matters because the 2026-08-10 rewrite stripped subject matter out
of descriptions while labels kept it (`"Identifying ATS Options"` vs *"List relevant
software platforms to establish the scope…"*). The situational anchoring the ceiling run
identified as missing is sitting in a field that is already stored and is discarded at
grading time. **This is the same missing-INPUT defect the Layer C rebuild found in the
WRITER, one stage later and never diagnosed** — so it is not a fourth wording pass, which
stopping condition #1 ruled out. Cheap to test against the ceiling run's own null (matched
vs deliberately unrelated rubric); change one field at a time.

**Also unused: `rubrics.anti_patterns` has never been read by anything.** Layer D scores
`milestones` and `soft_skills`; `anti_patterns` sits in every rubric untouched. It asks a
genuinely different question ("did they do this specific bad thing" rather than "did they
reproduce this specific good move"), which is a real reason it might discriminate where
milestones do not — but `PROMPT_LAYER_C_V1` requires them to carry `"[inferred]"` and
`"confidence": "inferred, unverified"`, so they are model guesses rather than clustered
evidence, i.e. strictly weaker than the thing already scoring 1.2:1. **Soft skills are
scored but have NEVER been separately validated** — the ceiling measurement was milestones
only. Both are cheap to null-test against the data this run produced.

**Data quality before the run — speaker roles are now as trustworthy as Naren's side.**
`ops/check_csm_speakers.py` found **87 of 113 speakers unclassified**, and classification
fails OPEN (an unlisted Joveo colleague is scored as THE CLIENT, so internal chatter becomes
coaching findings). Fixed by deriving the roster from Avoma rather than a hand-kept list:
`ops/backfill_csm_speaker_roster.py` (new) resolves each CSM transcript's `uuid[:8]` filename
suffix against the meetings list — the meetings window is **end-EXCLUSIVE**, measured — and
fetched **103/103** per-meeting rosters; `ops/derive_joveo_roster.py` (new) reads both sides
and identifies Joveo staff by `@joveo.com` email rather than `is_rep` (which mislabels
client-side contractors). 66 staff found, one unconfigured (`Shehzad karkhanawala`, added).
**`ego_trap/` does NOT read `speakers.json` at all** — it classifies from `csm_name` plus
`JOVEO_SPEAKER_NAMES` — so the authoritative data has to be fed INTO that list, which is
what makes the fetch count. 7 transcripts excluded via the new `run_ego_trap.py --exclude`
(applied BEFORE `run_id` is derived): 6 whose 417 `Unknown Speaker` turns cannot be
attributed, plus `sample_call_priya_001` which has no mapped CSM.

