# Corpus Contamination & Measurement-Harness Remediation (2026-08-15/16)

[Findings index](INDEX.md)

### Corpus contamination: 13.2% of the "client" pool was not client speech (2026-08-16)

Found while reading the clustering trial's scenarios. Three independent causes, all the same
failure mode: **`transcript_parser._classify` fails OPEN — anything it cannot identify becomes
CLIENT.** Fixes are recorded in `PROBLEMS_AND_FIXES.md`; harnesses are
`calibration/flag_interview_transcripts.py`, `calibration/fetch_avoma_meeting_meta.py`,
`calibration/check_employees_as_clients.py`, `ops/repair_speaker_rosters.py`.

| source | turns | fix |
| --- | --- | --- |
| job-interview calls (23) | 1,490 | quarantined to `recordings_excluded_interviews/` |
| unattributed speakers | 1,127 | new `SpeakerRole.UNATTRIBUTED` (PRODUCTION change) |
| Joveo staff read as client | 544 | `ops/repair_speaker_rosters.py`, 27 sidecars |
| **total** | **3,161 (−13.2%)** | 416 → 393 transcripts, 23,949 → 20,788 turns |

- **The largest coachable scenario was JOB INTERVIEWS — 822 turns, 27% of coachable volume.**
  Confirmed by reading: Naren says *"think of this lesson as an interview"* and *"specifically
  hiring for this role for my team"*, then the candidate narrates 13 years of work history.
  A candidate is not a Joveo name, so every turn entered the CLIENT pool. Career narration is
  highly self-similar so it clusters **~5x more tightly than real client discussion** — ~5% of
  calls produced 27% of coachable volume. Same disease as the documented
  `compensation_and_variable_structuring`, 21x larger.
- **`Unknown Speaker` came from `ops/fetch_avoma_recordings.py:107`**:
  `speaker_map.get(segment.speaker_id, "Unknown Speaker")` — Avoma's diarization heard a voice
  that was not on the calendar invite (dial-in, forwarded invite, shared room). It matched no
  roster entry and no Joveo name, so it fell through to CLIENT and became **the single largest
  "client" voice in the corpus**. **9 calls were 100% phantom — 706 turns from calls where no
  client was ever identified** (one was 229 of 349 turns). Now `SpeakerRole.UNATTRIBUTED`,
  returned BEFORE the roster lookup. Layer A/B gate on `role != CLIENT` so those turns are
  skipped; layer_b's response loop already broke on any non-Joveo role, so **response-window
  termination is byte-identical — the only change is that these turns can no longer be
  TRIGGERS.** `ego_trap/` has its own enum and is untouched.
- **`_classify` consults the ROSTER FIRST and `is_rep` decides outright — `JOVEO_SPEAKER_NAMES`
  is never reached when a roster entry exists.** So a colleague whose sidecar says
  `is_rep: false` is CLIENT and adding their name to the env var CANNOT fix it. The affected
  entries had `email` set to the literal string `"db"` or `"gm"` — a failed lookup leaking into
  the field. `kj` alone was 422 turns, the 11th-largest "client" voice.
- **An HR employee CSV (988 names) VALIDATED the conservative guard.** `deepika j`,
  `kaashvi seth`, `narasimharao tadi` are NOT employees — repairing them on inference would
  have deleted genuine client speech. `Ishraj Singh` (633 turns), `Vishi Agrawal` (530) and the
  other big partial matches are not employees either. Only exact/first+last matches were
  repaired; a shared token is not identity.
- **15 calls are genuinely internal (`RTX Prep`, `FLINT CRM de-brief`) and were ALREADY
  contributing zero client turns.** Internal calls were a non-issue; Avoma's `is_internal` flags
  only 7 and they contribute nothing. Do not spend effort here.

**AVOMA HAS GROUND TRUTH THE PIPELINE NEVER READS.** `GET /v1/meetings/{uuid}/` returns
`subject`, `purpose`, `is_internal`, `outcome`. **The trailing slash is required** (301
without it) and `/v1/meeting_types/` is **404** on this account — `purpose` arrives inline.
Auth is `Bearer $AVOMA_API_KEY`, same as `ops/fetch_avoma_recordings.py`.
**`purpose = "Exclude from Review"` is a WORKFLOW tag, NOT a quality judgment — 110 calls,
28.4% of the pool, and it is dominated by RECURRING CLIENT MEETINGS** (`Scale.ai<>Joveo:
Weekly check-in`, `Banfield || Career Site Weekly`, `Uber/Joveo - Weekly performance review`).
Excluding it would have destroyed the account-management calls the CS team exists to run. It
was nearly done on a misread; **sampling the subjects is what caught it**.

**THE DOMAIN-VOCABULARY TRAP FIRED THREE MORE TIMES IN ONE SESSION.** In a recruitment-
advertising corpus, `hiring`, `your resume`, `candidate`, `prep` and `quick connect` are the
SUBJECT MATTER, not meeting types. `"RTX || 'Engineers in Their Element' US Hiring Discovery"`
is a client call; `"Guidewire - Joveo Prep Call"` has `shmorris@guidewire.com` on it. Same
class as `Indeed` being a spaCy stopword. **Before adopting any keyword as a signal here,
check what it means to THIS business.** What survived: `your journey` (Naren's stock interview
opener, 8/8 recall on hand-verified calls, 2 false positives both caught by the account
signal) and the Avoma subject shape `<Role Title> - <Person> - Discussion N`.


---

### Measurement-harness remediation, R1-R3 (2026-08-15)

**Full detail — per-item status, every corrected number, the observation list and the
measurement lessons — is in `AUDIT_FINDINGS_2026-08-15.md` ("REMEDIATION LOG"). Continue the
work from `CONTINUE_PROMPT.md`.** Nine corrections landed, **zero conclusions reversed**; every
one moved in the direction that already supported the conclusion drawn. Two things belong here
because they cost money or silently corrupt a result:

- **Correct a statistic with `calibration/trial_grader_inputs.py --recompute`, never a plain
  re-run.** `main()` rebuilds items *before* consulting the checkpoint, which resumes only on an
  exact `n_items` match, and `--holdout` / `--conditions` / `--per-scenario` are **not recorded
  in the artifact** (F8, open). Guess one wrong and the run starts SCORING — ~180 paid calls for
  `clean_v2` alone. `--recompute` re-derives from the checkpoint and cannot reach Postgres or chat.
- **A point estimate and its CI must use ONE estimator, and `np.percentile` returns NaN if the
  sample holds a single `+inf`** (it interpolates `inf - inf`). `confirmB` shipped
  `[2.116, 3.645]` around a `D` of `2.114` from that first defect alone.

