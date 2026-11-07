# Golden dataset: Naren's own verdicts

The test set Ask Naren must pass before anything new goes to prod. Every case is a question
**Naren asked** and **his verdict** on the answer he got, said out loud while testing. Nothing
here was written from the prompt, so it cannot echo the prompt back
(see `../docs/findings/` and the memory note on eval cases).

## Files

| File | Tracked | What |
|---|---|---|
| `naren-2026-11-04.json` | yes | 11 graded cases + 1 timeout + 6 session-wide themes. The golden set. |
| `naren-2026-11-04.replay.json` | yes | The same session as one conversation, in `audit/live_conversation/converse.py` format. |
| `pull_turns.mjs` | yes | Pulls stored turns for a time window from `ask_naren.turns`. |
| `recordings/2026-11-04-naren/` | **no** (git-ignored) | `video.mp4`, `transcript.md`, `turns_raw.json`, `screenshots/`. |

`recordings/` is ignored on purpose: the repo is public, and the raw responses cite client
calls by name. On another machine, get the video from Drive
(the link is kept off this public repo; ask Harshil) and re-pull the turns
with `pull_turns.mjs`. The transcript exists only in that folder on Harshil's Mac.

## The 2026-11-04 session in one table

Prod Ask Naren (the old 19-intent router, not COMPOSE), Naren's account, thread 13.
"Video" is where the answer appears in the recording.

| Case | Video | Question (short) | Breadth | Naren's verdict |
|---|---|---|---|---|
| N1104-01 | 03:19 | How does Joveo's tracking work? | generic | partly right: too narrow (down-funnel only) |
| N1104-02 | 06:47 | How do I get my ATS to integrate? | generic | right: "the right amount of generic" |
| N1104-03 | 10:17 | Hire nurses, Indeed not enough | generic | right with gaps: "75%", missing funnel tracking + the why |
| N1104-04 | 13:17 | Craigslist via Joveo vs directly | specific | right: "a really good answer" |
| N1104-05 | 14:07 | What's the pricing for this? (follow-up) | specific | right with gaps: carried the thread; "% on top of media spend" is out of date, it is cost-per-apply |
| N1104-06 | 16:02 | What are title expansions? | specific | **wrongly declined**: it is job taxonomy (keywords = job titles) |
| N1104-07 | 18:10 | How do I get started with Joveo? | generic | **wrong**: gave job-feed steps; wanted the onboarding process (2-4 weeks, main stages) |
| (turn 8) | 21:26 | How does location targeting work? | generic | timed out (30s) |
| N1104-09 | 22:22 | same, asked again | generic | right with gaps: "great", add channel-specific + the why (commute) |
| N1104-10 | 24:04 | Which countries can Joveo post in? | generic | right: "good enough" |
| N1104-11 | 25:29 | Can I track organic traffic? | specific | right: his example of a good "why" |
| N1104-12 | 27:23 | What do I need for tracking setup? | generic | **wrong**: gave campaign-segmentation steps; missed pixel placement |

**4 right, 3 right with gaps, 1 partly right, 2 wrong, 1 wrongly declined, 1 timeout.**
Every outright failure is a generic question (01, 07, 12) or a wrong decline (06).
Specific questions all came out right or close.

## What Naren asked for (his closing summary, 28:45)

1. **Generic question, generic answer.** Broad sales-style questions get answered from one
   narrow call. "Wherever it's specific it works ... more effort needed when it's generic."
2. **Certified sources.** Connect Cortex and other product documentation, so answers are not
   limited to what came up on his calls.
3. **Explain the why** for campaign-management topics (not needed for integration).
   N1104-11 is his model of a good one.
4. **Ask a clarifying question** when the question is too wide ("get started with what? Are
   you looking to do programmatic?"). Also helps new joiners learn which questions to ask.

Also, at the start (00:54): **group the 49 situations into buckets** (tracking, integration,
campaign setup) instead of one A-to-Z list. He said it only matters if Ask Naren is meant
as a knowledge base people browse.

Two more things the recording shows that he did not list:
- **Stale facts.** N1104-05's wrong line was Naren's own words on a Feb 2024 call. Old calls
  can be out of date, and the grounding check can't catch that.
- **Wrong declines from intake.** N1104-06 was declined by the intake classifier
  (`out_of_scope`) before any search ran.

## How to test a new version against it

1. Start the service you want to test (VPN on). On Harshil's Mac the Neon host only resolves
   through public DNS, so pass `--hostaddr` (look the address up with
   `dig +short @8.8.8.8 <pooler host>`):
   ```bash
   cd Brain && ../.venv/bin/python ops/serve_ask_naren.py --hostaddr <ip>
   ```
   `COMPOSE` is a constant in `Brain/ops/serve_ask_naren.py` (True on
   `fix/ask-naren-plan-gather-write`). Flip it to compare the two paths.
2. Replay the session (it is one thread, so 05 still follows 04):
   ```bash
   python ask-naren/audit/live_conversation/converse.py \
     ask-naren/golden/naren-2026-11-04.replay.json \
     ask-naren/golden/recordings/runs/<run-name>.json
   ```
   Results go under `recordings/` because each response cites client calls by name and the repo
   is public. Message order = case order; the replay leaves out the timed-out turn 8.
3. Grade each answer against that case's `expected`:
   - **pass**: every `must` is met and no `must_not` is hit. A case with `also_acceptable`
     also passes on that.
   - **partial**: some `must` met, no `must_not` hit.
   - **fail**: a `must_not` is hit, or the core `must` is missed.
   Grade without knowing which version wrote the answer; shuffle the two versions' answers.
   Compare with `baseline`, which is what prod said on the day.
4. Count time too. Any answer that misses the 30s deadline fails (`must_finish_within_deadline`).

**Read it honestly.** It's 11 cases from one person in one session: a regression check and
direction-finder, not an accuracy rate. Cases 02, 04, 10 and 11 are guards, so a new version
must not get worse there. Cases 03, 06, 07, 09 and 12 also need outside documentation
(Cortex), so a version that answers only from Naren's calls may not be able to pass them.
Their `needs_outside_calls` field says so.

## Results

### 2026-11-06: new engine (COMPOSE, `work/ask-naren` @ 3465eba) vs prod, 2 runs

Blind read by a Sonnet reader (`build_blind_packet.py`, then `score_blind_packet.py`). Run files
are in `recordings/runs/` (`compose-run{1,2}.json`, `n1104-compose.*`, `reader/grades.json`).
**Calibration passed:** on prod's answers the reader matched Naren in 9 of 11 cases; both
misses were stricter than Naren (01 and 05 called fail where he said partly).

| Case | Prod | New run 1 | New run 2 |
|---|---|---|---|
| 01 tracking (generic) | fail | partial | pass |
| 02 ATS integration | pass | partial | pass |
| 03 nurses | partial | partial | partial |
| 04 Craigslist | pass | pass | pass |
| 05 pricing follow-up | fail | fail | pass |
| 06 title expansions | fail | pass | pass |
| 07 getting started (generic) | fail | pass | pass |
| 09 location targeting | partial | fail (declined) | partial |
| 10 countries | pass | partial | partial |
| 11 organic traffic | pass | fail (timed out) | pass |
| 12 tracking setup (generic) | fail | fail (declined) | pass |
| **Score (pass 2, partial 1)** | **10/22** | **10/22** | **19/22** |

What it says:
- **The new engine fixes what Naren complained about**, in both runs: broad questions (01, 07)
  and the wrong refusal (06).
- **It is not stable.** Run 1 scored the same as prod because of three failures run 2 didn't
  have: the grounding check threw away the location answer (09); organic traffic hit 30.0s
  (11); and the planner read "What do I need to do to get tracking setup?" as a follow-up to
  the previous answer (`from_conversation`) and declined (12). The planner made that same
  misread in run 2 too and only got lucky. Run 1 also repeated the stale "% of media spend" fee (05).
- **Neither run fixes 03 or 10.** 03 needs funnel tracking + quality-metric optimization, which
  Naren said may need documentation. 10 doesn't offer a tailored country list.
- **Speed is not worse:** median 18s / 16s against prod's 19s; none over 30s, but one at 30.0s.
- Two runs is too few to say which run is typical. Run it more times before deciding.

### 2026-11-07: after the three fixes (lenient JSON, rework fallback, `.txt` call match), 3 runs

Same blind read (Sonnet; calibration passed 9/11, same two stricter-than-Naren misses).
Files: `recordings/runs/fixed-run{1,2,3}.json`, `n1104-fixed.*`, `reader2/grades.json`.

| Case | Prod | Run 1 | Run 2 | Run 3 |
|---|---|---|---|---|
| 01 tracking (generic) | fail | pass | pass | pass |
| 02 ATS integration | pass | pass | pass | pass |
| 03 nurses | partial | partial | fail (timed out) | partial |
| 04 Craigslist | pass | pass | pass | fail (grounding) |
| 05 pricing follow-up | fail | fail (stale % fee) | pass | partial |
| 06 title expansions | fail | pass | pass | pass |
| 07 getting started (generic) | fail | partial | pass | pass |
| 09 location targeting | partial | partial | partial | partial |
| 10 countries | pass | partial | partial | partial |
| 11 organic traffic | pass | fail (grounding) | partial | partial |
| 12 tracking setup (generic) | fail | fail (timed out) | pass | pass |
| **Score** | **10/22** | **12/22** | **17/22** | **15/22** |

- **Every run beats prod**, and the spread narrowed (12–17 against 10–19 before the fixes),
  but the average barely moved (14.7 against 14.5). The fixes removed failure modes; they
  did not raise answer quality.
- **Still 4 of 33 unanswered (12%)**: 2 timeouts at 30s, 2 grounding drops (cause not logged
  by the server; the in-process diagnosis found none in 15 tries on the broad questions).
- **Consistent wins on what Naren raised:** 01, 06, 07, 12 (tracking setup planned as a
  follow-up in 2 of 3 runs again, but answered).
- **Consistent losses against prod:** 10 never offers a tailored country list; 11 loses the
  "why" Naren praised. The "why" ticket covers 03/09/11.
- 05's stale "% of media spend" fee came back in one run of three.

### 2026-11-07: the four general fixes (writer principles, reworks search, the CSM's words searched, citation corrected), 3 runs

Replaces the `.txt` and declined-rework hot fixes. Same blind read (Sonnet; calibration passed 9/11,
the same two stricter-than-Naren misses). Files: `recordings/runs/general-run{1,2,3}.json`,
`n1104-general.*`, `reader3/grades.json`, `service-general.log`.

| Case | Prod | Last 1 | Last 2 | Last 3 | New 1 | New 2 | New 3 |
|---|---|---|---|---|---|---|---|
| 01 tracking (generic) | fail | pass | pass | pass | pass | pass | pass |
| 02 ATS integration | pass | pass | pass | pass | pass | pass | pass |
| 03 nurses | partial | partial | fail (timeout) | partial | partial | partial | partial |
| 04 Craigslist | pass | pass | pass | fail (grounding) | pass | pass | pass |
| 05 pricing follow-up | fail | fail | pass | partial | fail | fail | fail |
| 06 title expansions | fail | pass | pass | pass | pass | pass | pass |
| 07 getting started (generic) | fail | partial | pass | pass | partial | pass | partial |
| 09 location targeting | partial | partial | partial | partial | partial | pass | fail (grounding) |
| 10 countries | pass | partial | partial | partial | partial | partial | pass |
| 11 organic traffic | pass | fail (grounding) | partial | partial | pass | pass | pass |
| 12 tracking setup (generic) | fail | fail (timeout) | pass | pass | pass | pass | pass |
| **Score** | **10/22** | **12** | **17** | **15** | **16/22** | **18/22** | **16/22** |

- **Average 16.7 against 14.7 for the last runs and 10 for prod; the worst run (16) beats the last
  runs' worst (12).** 32 of 33 answered, **0 timeouts** (last runs: 3), slowest 28.4s.
- **11 organic traffic now passes 3/3** (the "why" Naren praised is kept); 04 and 12 pass 3/3.
- **05 got worse: the stale "% on top of media spend" is in all 3 runs** (last runs: 1 of 3). Every
  run, old and new, cites the same Feb 2024 call; the new "keep his offers and conditions" principle
  keeps that line instead of sometimes dropping it, and "go with the most recent call" cannot help
  because no newer call contradicts it. Needs the fact marked stale or a documentation source.
- 09's one decline: two near-verbatim long quotes (~80% overlap) -- the out-of-scope question of
  accepting near-verbatim quotes. 07 still says "up to two weeks" in 2 runs, not Naren's 2-4.
- The planner never chose a rework on the golden set this time (0/33), and `citation_corrected`
  never fired, so fixes 2 and 4 were not exercised here -- only on the held-out set below.
- Writer output got shorter: median 890 completion tokens against 1,202, answers ~1,600 characters
  against ~1,970, write median 7.8s against 11.5s.

**Held-out regression check** (`audit/live_conversation/conversations.json` + `conversations_25_new.json`,
41 turns, not tuned on). Old code (`heldout-before-*`) against new code twice (`heldout-after-*`,
`heldout-after2-*`), Sonnet pairwise blind A/B per turn (`pairwise{1,2}/verdicts.json`, keys beside).

| | New better | Old better | Tie | Of old's wins, new failed to answer |
|---|---|---|---|---|
| Run 1 (laptop slept during part of it) | 16 | 12 | 13 | 7 (4 timeouts, 3 grounding) |
| Run 2 (laptop kept awake) | 16 | 9 | 16 | 3 (2 timeouts, 1 broken JSON) |

- **Where both answered, new wins 13-5 and 14-6.** The reader's reasons: stays on what was asked,
  client-ready wording, less padding, closer to its quote.
- **Reworks:** every rework answered in both runs. Old code declined "ok going back to the first
  one, what do i tell them" as `follow_up_ungrounded`; new code answered it both times.
- **Timeouts are the cost.** Old code 0/41; new code 2/41 on a clean run (plus 1 broken-JSON error,
  the known writer failure). Gather median 3.0-4.0s against 2.7s, held-out write median 10.8s against
  7.9s, prompt median ~57k chars against ~48k: the message search fills the 24-exchange cap more
  often. The two clean-run timeouts had a slow planner (8.8s on an 11-character vague follow-up) or a
  slow embedding (4.4-4.7s) ahead of the write.
- Whether fix 3 (the message as an extra search) helps or hurts on its own is **not isolated**: it
  ships together with the other three, and only an ablation (fix 3 off) would separate it.
- `citation_corrected` fired once per held-out run, both `.txt`-only slips.

### 2026-11-07 (later): the "why" line, a JSON retry, a quote-length guard; fix 3 on vs off, 2 runs each

Added: a writer principle to take Naren's reasons for results from anywhere in the material; one
retry on a broken-JSON writer reply; a citation is re-pointed to another call only for a quote of
8+ words (`grounding.MIN_CORRECTED_QUOTE_WORDS`), and a `.txt`-only difference counts as the named
call (`grounding.call_key`). Fix 3 (the CSM's words as a search) is now `composing.SEARCH_CSM_WORDS`.
Same blind read (calibration passed 9/11). Files: `why-{on,off}-run{1,2}.json`, `n1104-why.*`,
`reader4/grades.json`, `service-why-{on,off}.log`.

| Case | Prod | #3 on, 1 | #3 on, 2 | #3 off, 1 | #3 off, 2 |
|---|---|---|---|---|---|
| 01 tracking | fail | pass | pass | pass | pass |
| 02 ATS | pass | pass | pass | pass | pass |
| 03 nurses | partial | partial | partial | partial | partial |
| 04 Craigslist | pass | pass | pass | pass | pass |
| 05 pricing | fail | fail (stale %) | pass | pass | pass |
| 06 title expansions | fail | pass | pass | pass | pass |
| 07 getting started | fail | partial | partial | pass | partial |
| 09 location | partial | partial | partial | fail (grounding) | partial |
| 10 countries | pass | partial | pass | partial | pass |
| 11 organic | pass | pass | partial | pass | pass |
| 12 tracking setup | fail | pass | pass | pass | pass |
| **Score** | **10** | **16** | **18** | **18** | **19** |

- **The "why" line did not fix 03.** The playbook carrying Naren's "feedback loop into hire tracking
  ... start optimizing towards that" quote was in the writer's material in all 4 runs; all 4 answers
  still miss funnel drop-offs and optimizing to quality, exactly as prod did.
- **Fix 3 off scored 18.5 against 17 on, with no speed difference** (median answer 18.2s vs 17.1s,
  0 timeouts either way). Two runs each: within run-to-run noise, but no sign fix 3 helps.
- 05's stale "% of spend" fee: 1 of 4 runs (the previous round: 3 of 3).
- 0 timeouts in 44 answers; 1 grounding decline (09 again).

**Held-out with fix 3 off and the why line kept** (`heldout-final-*`, `pairwise3/`): new better 13,
old better 15, tie 13. Of old's 15, 7 are turns new did not answer: 4 in a gateway stall (three
requests never got a planner reply in 30s), 3 grounding declines on 1,300-1,550-character quotes that
were 99.8% verbatim. **Where both answered: 10-8, against 14-6 and 13-5 for fix 3 on without the why
line.** Two things changed at once, so the drop is not attributed; the why line is the likelier cause
-- it licenses material from other situations, and the reader's reasons for old's wins include
"jumps to an unrelated discussion" -- the failure in `docs/findings/answer-failure-modes.md`.
Long quotes are now the main grounding failure: asking the writer for a one- or two-sentence quote
is the cheap next fix.

**Why line removed; quote asked to be one or two sentences; fix 3 still off** (`heldout-shortq-*`,
`pairwise4/`, `pairwise5/`). Quotes: median 302 chars (was 456-513); writer median 7.2s, 714
completion tokens; 1 grounding decline (was 3); 2 timeouts, both reworks (planner 9.6s; a 23s
vector-store stall). Against old code: new 19, old 15, tie 7 (16-12 where both answered).
**Head-to-head, one packet:** fix 3 on + long quotes (`heldout-after2-*`) beat fix 3 off + short
quotes 18-13 (15-10 where both answered), with the reader told not to favour longer excerpts; its
reasons are content (drift, invented steps, unsupported claims). Fix 3 and quote length both differ
between the two, so the gap is not attributed -- but every held-out read with fix 3 on came out
better against old code than every read with it off, while the golden set showed no difference.
Cross-packet margins are not comparable (ties ranged 2-16 across reads).

### 2026-11-08 early: the candidate release -- fix 3 on, short quotes, no why line ("stage X")

Files: `x-run{1,2}.json`, `n1104-x.*`, `reader5/grades.json`, `heldout-x-*`, `pairwise6/`,
`service-x.log`, `night.log` (network checks; a VPN/ISP slowdown 05:00-06:00 IST was waited out --
the database delivered ~23 KB/s and one embedding took 13 s, so nothing ran until both recovered).

| Case | Prod | X run 1 | X run 2 |
|---|---|---|---|
| 01 tracking | fail | pass | pass |
| 02 ATS | pass | pass | pass |
| 03 nurses | partial | partial | partial |
| 04 Craigslist | pass | pass | pass |
| 05 pricing | fail | fail (stale %) | fail (stale %) |
| 06 title expansions | fail | pass | pass |
| 07 getting started | fail | fail (timeout) | pass |
| 09 location | partial | pass | pass |
| 10 countries | pass | partial | partial |
| 11 organic | pass | pass | pass |
| 12 tracking setup | fail | pass | pass |
| **Score** | **10** | **16** | **18** |

- Calibration passed (9/11, the usual two). 1 timeout in 22.
- **Held-out against old code: new 20, old 11, tie 10; 18-11 where both answered.** 40 of 41 turns
  answered or correctly routed; **0 grounding declines**, 1 timeout. Quote median 235 chars.
- Meets the bar set for release: golden at 16 or above, held-out better than old code.

**Can a search reach Naren's "why"?** (`why_probe.txt`, gather only.) Yes: a search for the reason
behind "hire nurses faster" returns at rank 1 "we are gonna assign a lot more weightage towards the
client interviews ... and start optimizing towards" and attaches the down-funnel tracking playbook; for
location it returns "we'll look at where talent lives, where talent works". The planner does not
write such searches on its own. Asked to in a bullet (`y-run{1,2}.json`), it wrote one in 1 of 2
runs for 03, and that one named the topic ("why programmatic distribution works better for
healthcare"), not the reason. Stopped there; replaced by a dedicated `why_search` field (below).

**The `why_search` field ("Y2", `composing.SEARCH_FOR_THE_WHY`)** -- X plus a planner field for one
search aimed at Naren's reason. Files: `y2-run{1,2}.json`, `n1104-xy2.*`, `reader6/`, `heldout-y2-*`,
`pairwise7/` (X vs Y2 head-to-head), `service-y2.log`.
- Golden, same packet as X: Y2 20 and 16, X 16 and 18 -- noise. **03 still partial in all four**:
  one Y2 answer mentioned "leading indicators (shortlists, interviews) and lagging indicators
  (hires)", but none stated drop-offs per stage or optimizing to the client's quality metrics.
- Held-out head-to-head: **X 14, Y2 10, tie 17; 10-10 where both answered.** Y2 lost 3 turns X
  answered (2 `no_close_match`, 1 grounding); writer median 11.5s against 9.1s.
- **Verdict: left OFF.** No quality gain, more declines, slower, and its target case not fixed.
  Naren's 03 reasoning is reachable by a hand-written search; getting the planner to write that
  search, and the writer to make the argument from it, is not solved.

### 2026-11-06: where the new engine's time goes (`ask-naren/audit/time_compose_stages.py`)

22 messages (the session twice), in-process, same 30s deadline. Median answer 16.6s, max 26.5s.

| Stage | Median | Max | Share of all time |
|---|---|---|---|
| Write (one LLM call, gemini-3.6-flash) | 11.6s | 22.7s | **68%** |
| Gather (embed the searches + Pinecone + playbooks) | 2.5s | 10.7s | 17% |
| Plan (one LLM call) | 1.8s | 5.9s | 15% |

- **Speed lives in the writer.** A fast decision model (Jev) can only replace part of the
  planner, which is 15% of the time, because the planner also writes the search queries.
- **2 of 22 answers failed because the writer returned broken JSON** (extra text after the
  object; a raw control character). Users would see these as failures. Fixing it is cheap:
  parse leniently, or retry once.
- 1 of 22 was dropped by the grounding check (location targeting again).
- Tracking setup (11) was planned as `from_conversation` in **both** passes again. The
  misread is reproducible, not bad luck.

## Adding the next session

Naren said he'll keep testing. For each new session:
1. Get the recording and pull the turns: `cd frontend && node ../ask-naren/golden/pull_turns.mjs
   <fromISO> <toISO> <out.json>` (reads `frontend/.env.local`; never put the URL on the command line).
2. Keep video, transcript, raw turns and screenshots in `recordings/<date>-<who>/` (ignored).
3. Find the video offset: turn `answered_at` against a frame showing that answer.
   Screenshots: `ffmpeg -ss <mm:ss> -i video.mp4 -frames:v 1 -vf crop=1440:765:0:157 out.png`
   (crops a 1080p Meet screen-share to the app, without the webcam).
4. Add a `<date>.json` with cases in the same shape. `naren_said` holds his words; `expected`
   only restates what he said. If he didn't say what the answer should contain, write the
   verdict and leave `must` short. Don't fill the gap yourself.
