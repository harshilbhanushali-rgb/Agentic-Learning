/* Shared domain types for the CS-platform UI. */

export type Mode = 'veteran' | 'newbie';

/* ── Workspace ─────────────────────────────────────────────── */

export interface Moment {
  time: string;
  quote: string;
  source: string;
}

export interface EgoTrap {
  day: string;
  account: string;
  meetingType: string;
  question: string;
  applied: number;
  missed: number;
  modules: number;
  failureStories: number;
  duration: string;
  source: string;
  participants: number;
  generatedAt: string;
  appliedMoments: Moment[];
  missedMoments: Moment[];
}

export type PrepStatus = 'ready' | 'in-progress' | 'cold';
export type WaterfallState = 'done' | 'active' | 'locked';

export interface WaterfallStep {
  state: WaterfallState;
  kind: string;
  label: string;
  meta: string;
}

export interface MeetingClip {
  label?: string;
  quote: string;
  meta: string;
}

export interface RadarMeeting {
  id: number;
  day: string;
  time: string;
  relative: string;
  account: string;
  title: string;
  tags: string;
  prepStatus: PrepStatus;
  prepLabel: string;
  industry: string;
  clip: MeetingClip;
  tip: string;
  waterfall: WaterfallStep[];
}

export type TestStatus = 'complete' | 'active' | 'locked';

export interface TestQueueItem {
  id: number;
  title: string;
  tier?: number;
  phase?: number;
  level: string;
  scored?: number | null;
  status: TestStatus;
  time: string | null;
  note: string | null;
}

export interface KnowledgeDrop {
  id: number;
  type: string;
  title: string;
}

export interface NewbieNextUp {
  kind: string;
  desc: string;
  meta: string;
}

export interface NewbieTrack {
  day: number;
  totalDays: number;
  phase: number;
  totalPhases: number;
  phaseLabel: string;
  progress: number;
  nextUp: NewbieNextUp[];
}

export type BloomState = 'done' | 'active' | 'next' | 'locked';

export interface BloomStage {
  label: string;
  state: BloomState;
  note: string;
}

/* ── Library ───────────────────────────────────────────────── */

export interface SpotlightCourse {
  id: number;
  title: string;
  desc: string;
  tags: string[];
  modules: number;
  readTime: string;
}

export type Spotlight = Record<Mode, SpotlightCourse>;

export interface Course {
  id: number;
  title: string;
  desc: string;
  tags: string[];
}

export interface CourseSectionData {
  title: string;
  courses: Course[];
}

export interface Chapter {
  num: number;
  title: string;
  summary: string;
}

export type CaseStudyStatus = 'live' | 'historical';

export interface CaseStudy {
  id: number;
  account: string;
  headline: string;
  sector: string;
  region: string;
  monthsActive: number;
  total: number;
  status: CaseStudyStatus;
  justDropped: boolean;
  participants: number;
  context: string;
  chapters: Chapter[];
}

export interface FailureEntry {
  id: number;
  deal: string;
  category: string;
  lesson: string;
  quarter: string;
  fullPostMortem: string;
}

/* -- Ask Naren -------------------------------------------------------------------------
 * The response shape of the Ask Naren service (Brain/ask_naren/service.py, POST /ask),
 * mirrored exactly. The proxy at app/api/ask-naren returns it unchanged, so these types
 * describe the service's contract and must not drift from it.
 *
 * Discriminated on `outcome`, which is what makes the three render paths exhaustive: an
 * answer always carries a citation, a decline never does. The service guarantees this --
 * an answer that fails its grounding gate becomes a decline rather than an answer with a
 * missing citation. */

export interface AskNarenCitation {
  /** What a CSM reads. The raw call filename for now; issue #4 resolves it to an account
   *  and a date. Deliberately separate from `call_filename` so that resolution is not a
   *  shape change for every caller. */
  label: string;
  call_filename: string;
  /** ABSENT ON A LAYER C ANSWER (issue #17). A playbook evidence quote records the call it
   *  came from, not a `kb_pairs` row, so there is no pair to point at — and inventing one
   *  would send an engineer tracing a bad answer to an exchange it does not rest on. */
  pair_id?: number;
  scenario_key: string;
}

export interface AskNarenMatch {
  /** In gemini-embedding-2@3072 space -- NOT comparable to any threshold in Brain's
   *  tuning.yaml, which was fitted in bge@768. Recorded, never rendered as a score. */
  cosine: number;
  scenario_key: string;
  /** Position in the candidate shortlist the answer was grounded at. Always 1 on the
   *  shipped path, where the shortlist is one exchange long (see ADR 0005). */
  rank: number;
}

/** What intake decided about the message, echoed on every response the service composes
 *  (issue #14).
 *
 *  It exists to make a SILENTLY FAILING intake visible. Intake degrades to answering the
 *  message as written when the model or gateway misbehaves, so a broken intake and a working
 *  one both return a normal answer — without this there is nothing to tell them apart.
 *
 *  Optional because the proxy synthesises an unreachable decline that never reached the
 *  service, so no intake ran for it. */
export interface AskNarenIntake {
  intent: string;
  /** What actually got embedded — the client's words with the CSM's framing stripped, which
   *  is frequently not what the CSM typed. Intake is asked for a verbatim span of the
   *  message, but that is a prompt rule rather than a guarantee: it has been observed
   *  composing one instead, once flipping "their side" to "our side". Shown here so a bad
   *  extraction is visible rather than silent. Always derived from the CSM's own message,
   *  never from Naren's calls. */
  retrieval_query: string;
}

export interface AskNarenAnswer {
  outcome: 'answered';
  intake?: AskNarenIntake;
  answer: string;
  /** The verbatim fragment of Naren's real reply the answer rests on. Verified server-side
   *  by the grounding gate before it is ever sent. */
  quote: string;
  citation: AskNarenCitation;
  /** ABSENT ON A FOLLOW-UP (issue #16). A follow-up is answered from the thread and the
   *  grounding source already cited, with no retrieval at all, so there is no cosine and no
   *  rank — the same reason an out-of-scope decline carries no `match`. Reporting one would
   *  put a fabricated number into the record decline-rate calibration later reads. The
   *  `citation` still says exactly which exchange the answer rests on. */
  match?: AskNarenMatch;
  /** PRESENT ONLY ON A CONTRAST (issue #21): the CSM's own reply, which `answer` is a
   *  comparison against. Rendering the comparison without it would be half an answer.
   *
   *  It is the CSM's own text echoed back — a verbatim span of their message, enforced
   *  server-side — never anything drawn from Naren's calls, so it cannot carry ungrounded
   *  content. That property, not its provenance, is what makes it safe to render.
   *
   *  Its presence is what switches the card into contrast layout, rather than a second
   *  discriminator beside `outcome`: nothing about the guarantee differs here, so a fifth
   *  outcome would say something untrue about trust. */
  my_reply?: string;
}

/** Where each one comes from, because they must stay distinguishable to whoever is
 *  debugging (issue #6): `no_close_match` and `grounding_unverified` are the answerer
 *  deciding it cannot ground an answer -- the tool working correctly. `service_error` is the
 *  service's own 503, raised when answering threw. `service_unreachable` is synthesised by
 *  the proxy when the service could not be reached or timed out at all.
 *
 *  The last two are faults; the first two are not. Rendering them identically to a CSM is
 *  deliberate, but COLLAPSING them would hide an outage behind what looks like normal
 *  conservative behaviour, so the reason codes stay distinct all the way through.
 *
 *  `service_busy` (issue #32) is a THIRD kind, and neither a fault nor a judgement about
 *  the question: too many people are asking at once. It matters most that it stays
 *  separate from `no_close_match` — a capacity problem wearing a quality problem's clothes
 *  would make the tool look like it was working perfectly and simply declining a lot, and
 *  the decline-rate reads would quietly be measuring load instead of coverage. */
export type AskNarenDeclineReason =
  | 'no_close_match'
  | 'grounding_unverified'
  /** Decided by intake BEFORE anything is searched (issue #14): the question wants a fact
   *  about Joveo's product, pricing or contracts, which is not what Naren's call
   *  transcripts contain. Distinct from the two above because rewording cannot help — which
   *  is exactly why it is a decline and not a clarify. Carries no `match`: nothing was
   *  searched, so there is no cosine to report. */
  | 'out_of_scope'
  /** A follow-up (issue #16) whose answer could not be grounded in the exchange the thread
   *  carried forward. Distinct from `no_close_match` because nothing was searched: the
   *  follow-up path deliberately runs no retrieval, so this says "Naren did not say that in
   *  THAT call", not "nothing close exists". Asking it as a fresh question is the useful
   *  next move, and that is what makes it its own reason. */
  | 'follow_up_ungrounded'
  | 'service_error'
  | 'service_unreachable'
  /** Too many questions at once (issue #32). The service answers a bounded number
   *  concurrently — the gateway allows 8 requests in flight per API key, shared across chat
   *  and embeddings, operated at 6 — and queues the rest. This is the caller who arrived
   *  past what the queue can serve inside its deadline, so it is refused immediately rather
   *  than accepted and failed later: waiting out a deadline to be told nothing is strictly
   *  worse than being told now.
   *
   *  The ONE decline worth simply retrying, unchanged. Arrives as HTTP 429 with a
   *  `Retry-After` header, so a busy lunchtime does not look like an outage to anything
   *  counting 5xx. Carries `retry_after_seconds`. */
  | 'service_busy'
  /** Admitted, then ran out of its time budget (issue #32). Distinct from `service_busy`,
   *  which was never admitted, and from `service_error`, where something actually broke:
   *  here the service simply stopped rather than leave a CSM on a spinner past the point
   *  where an answer is still useful. HTTP 504. A rising rate of these means the cost
   *  estimate the queue depth is sized from has drifted. */
  | 'deadline_exceeded';

export interface AskNarenDecline {
  outcome: 'declined';
  intake?: AskNarenIntake;
  reason: AskNarenDeclineReason;
  /** Already written for a CSM to read. Render it as-is; do not compose a message from
   *  `reason` in the frontend, or there are two sources of truth for the same sentence. */
  message: string;
  match?: AskNarenMatch;
  /** PRESENT ONLY ON `service_busy` (issue #32): roughly how long until there is room,
   *  derived from the actual queue depth rather than being a fixed suggestion. The same
   *  number appears inside `message`, which is what gets rendered — this field exists so
   *  anything that wants to act on it (a retry, a countdown) does not have to parse prose.
   */
  retry_after_seconds?: number;
}

/** Ask Naren asking for something back instead of answering — decided BEFORE retrieval, so
 *  nothing was searched and nothing is grounded (see `ask-naren/CONTEXT.md`).
 *
 *  NOTE THE ABSENT FIELDS. There is no `answer`, `quote` or `citation` here, and that is
 *  structural rather than incidental: the guarantee is that unverified text never reaches a
 *  CSM in any field, and a shape with no such field cannot carry one. Do not add them.
 *
 *  Produced when intake decides the message names a topic without carrying the client's
 *  own words — searching on a bare summary reaches a different part of the corpus than
 *  searching on what was really said (issue #14). */
export interface AskNarenClarify {
  outcome: 'clarify';
  intake?: AskNarenIntake;
  /** The question to put to the CSM, written by the service. Rendered as-is, for the same
   *  reason `message` is on a decline. */
  question: string;
}

/** An answer built from STORED ROWS, with no model call at all (issues #19, #20).
 *
 *  ITS OWN OUTCOME, not `answered`, and the distinction is the guarantee rather than the
 *  layout. `answered` means a model wrote prose and the grounding gate verified a quote
 *  against a real source. `rendered` means nothing was generated, so there is nothing to
 *  verify — a rendered list of the coachable scenarios cannot invent a 35th, and a rendered
 *  exchange cannot drift from the exchange. Collapsing the two would make "answered" mean
 *  two different things about trust.
 *
 *  `kind` chooses the layout the same way `outcome` chooses the component. Five kinds share
 *  one outcome because they share one guarantee; five outcomes would make the union longer
 *  for no behavioural difference. */
export interface AskNarenScenarioRef {
  scenario_key: string;
  description: string;
}

export interface AskNarenExchange {
  client_said: string;
  naren_replied: string;
}

export type AskNarenRendered =
  | { outcome: 'rendered'; kind: 'discovery'; intake?: AskNarenIntake;
      /** FALSE on the live taxonomy, measured 2026-09-09: every scenario carries
       *  `primary_topic = 'ungrouped'` and the primary-topic hierarchy is recorded as
       *  rejected. When false, `topics` is empty and `scenarios` is the flat list — showing
       *  34 situations under one heading called "ungrouped" would invent a category. */
      grouped: boolean;
      topics: { topic: string; scenarios: AskNarenScenarioRef[] }[];
      scenarios: AskNarenScenarioRef[];
      total: number }
  | { outcome: 'rendered'; kind: 'frequency'; intake?: AskNarenIntake;
      scenarios: (AskNarenScenarioRef & { support_calls: number; call_coverage: number | null })[];
      total: number;
      /** Says what is being ranked. Rendered as-is — it is the qualifier that stops "most
       *  common" being read as a fact about clients rather than about this corpus. */
      basis: string }
  | { outcome: 'rendered'; kind: 'show_exchange'; intake?: AskNarenIntake;
      exchange: AskNarenExchange; citation: AskNarenCitation; match: AskNarenMatch }
  | { outcome: 'rendered'; kind: 'what_happened_next'; intake?: AskNarenIntake;
      exchange: AskNarenExchange;
      following: (AskNarenExchange & { scenario_key: string })[];
      /** True when nothing followed it in the call. An empty list is something a CSM has to
       *  interpret; this is an answer. */
      is_last: boolean; citation: AskNarenCitation }
  /* The five a scenario's Layer C playbook answers by being rendered (issue #18).
     `scenario_key` is on every one of them because these answers show the PLAY, derived
     from many calls — so for three of the five there is no single call to point at, and the
     scenario is the only thing that makes a misroute visible.

     THE OTHER TWO DO POINT AT A CALL, one per quote. `phrasing` and `pitfalls` show Naren's
     verbatim words from a real client call, so each quote carries its own source — a
     verbatim quote a CSM cannot trace is the bare assertion ADR 0002 says a citation
     exists to prevent. */
  | { outcome: 'rendered'; kind: 'sequence'; intake?: AskNarenIntake;
      scenario_key: string; steps: string[] }
  | { outcome: 'rendered'; kind: 'phrasing'; intake?: AskNarenIntake;
      scenario_key: string;
      /** Phrase and quote are one-to-one here, so unlike a Layer C `answered` response
       *  (ADR 0009) there is no part of this that a quote does not cover — which is why
       *  this is the one rendered kind that keeps the accent border.
       *
       *  `label` is what a CSM reads and `call` is the raw filename an engineer traces
       *  with, the same split as `AskNarenCitation`. `label` falls back to `call`, so it
       *  is never empty. */
      phrases: { phrase: string; quote: string; call: string; label: string }[] }
  | { outcome: 'rendered'; kind: 'pitfalls'; intake?: AskNarenIntake;
      scenario_key: string;
      pitfalls: { text: string;
                  evidence: { quote: string; call: string; label: string }[] }[] }
  | { outcome: 'rendered'; kind: 'scenario_check'; intake?: AskNarenIntake;
      asked_about: string; scenario_key: string;
      /** WHEN the play applies. Deliberately not a yes/no — whether it fits a live client
       *  is a judgement Ask Naren has only the CSM's own sentence for. */
      applies_when: string }
  | { outcome: 'rendered'; kind: 'play_confidence'; intake?: AskNarenIntake;
      scenario_key: string;
      /** Counted from the LIVE document, so they describe what the play rests on today.
       *  These lead the card. */
      moves: number; quotes: number;
      /** How many moments were CONSIDERED when the play was built — set before the verbatim
       *  snap dropped any, and capped by the builder's selection limit. Measured 2026-09-09:
       *  25 of 33 live playbooks sit exactly on that cap, so read bare it is a constant, and
       *  it can invert (50 → 8 quotes; 16 → 9 quotes). Secondary, and always rendered with
       *  `n_evidence_capped`. */
      n_evidence: number; n_evidence_capped: boolean;
      basis: string }
  /** Which accounts a situation has come up with (issue #22), so a CSM can tell a
   *  one-client quirk from a pattern across the book. The only rendered kind that reads a
   *  NEIGHBOURHOOD rather than one nearest exchange — its question has no single-exchange
   *  form. */
  | { outcome: 'rendered'; kind: 'where_else_seen'; intake?: AskNarenIntake;
      asked_about: string;
      /** The nearest exchange's scenario, and how many of the scanned exchanges share it.
       *
       *  RENDER BOTH. This answer is an aggregate over ~25 neighbours, and the top-20
       *  neighbourhood is measured at a mean of only 6.19/20 same-situation — so some of
       *  the accounts listed are about something else. Without these a CSM cannot tell a
       *  genuine book-wide pattern from a wide, incoherent neighbourhood, which is the
       *  entire discrimination this intent provides. It is also the only thing that makes a
       *  misroute visible here, since the answer names no single call. */
      scenario_key: string;
      same_scenario: number;
      /** Named accounts first, each ranked by what it carries; then the calls whose client
       *  the recorded data does not state unambiguously, listed by raw filename.
       *
       *  `named` is the whole distinction and must drive how the row renders. ~31% of
       *  citable calls are opaque UUIDs, and 40 of those 323 carry several external
       *  participant domains — one measured example is a brand and its agency. So an
       *  unnamed row is a real exchange whose client is genuinely unknown, NOT a guess and
       *  NOT something to drop: dropping under-reports the spread, guessing prints the
       *  wrong client. */
      accounts: { account: string; named: boolean; exchanges: number; calls: number }[];
      /** How many clients this really is, as a RANGE. Each unnameable call could be a new
       *  client or one of the named ones. Render both bounds — a single number states one
       *  end of the range as a fact.
       *
       *  RENDER THE RANGE FROM `accounts_at_least`, NOT from `accounts_named`. They differ
       *  exactly when nothing could be named: `accounts_named` is 0 there, but exchanges
       *  that exist came from somebody, so "between 0 and 3 accounts" asserts something
       *  impossible. `accounts_named` stays available as the plain fact of how many the
       *  data could name. */
      accounts_named: number;
      accounts_at_least: number;
      accounts_at_most: number;
      unnamed_calls: number;
      exchanges: number;
      basis: string }
  /* The two composites (issue #23). BOTH RENDER, and that is the guarantee rather than the
     layout: ADR 0009 warns that stitching a Layer C summary onto a Layer B answer inherits
     the weaker of the two, so these compose only rendered paths and inherit neither. The
     cost is real — neither can summarise or tailor its advice to a particular client; they
     assemble what is on file and let the CSM read. */
  | { outcome: 'rendered'; kind: 'call_prep'; intake?: AskNarenIntake;
      asked_about: string;
      /** The likely ground, most-represented first: what tends to come up, the recorded
       *  play for each, and one real exchange to read.
       *
       *  `has_play` false means no play is RECORDED for that situation — not that there is
       *  none. Render the difference; an empty step list alone reads as the second. */
      scenarios: {
        scenario_key: string;
        description: string;
        exchanges: number;
        has_play: boolean;
        steps: string[];
        example: AskNarenExchange & { citation: AskNarenCitation };
      }[];
      /** How many distinct situations the neighbourhood held, which may exceed the number
       *  shown — a CSM should know the list was trimmed rather than exhaustive. */
      scenarios_found: number;
      exchanges: number;
      basis: string }
  | { outcome: 'rendered'; kind: 'improve_at_move'; intake?: AskNarenIntake;
      asked_about: string; scenario_key: string;
      /** TRUE when the CSM's own words picked one move out, FALSE when nothing matched and
       *  this is the whole play instead. The page must say which — presenting all the moves
       *  as though they were the one thing asked about is a quiet lie about what was
       *  understood. */
      focused: boolean;
      moves: { name: string; criterion: string;
               evidence: { quote: string; call: string; label: string }[] }[];
      pitfalls: { text: string;
                  evidence: { quote: string; call: string; label: string }[] }[];
      basis: string }
  | { outcome: 'rendered'; kind: 'coverage_check'; intake?: AskNarenIntake;
      asked_about: string;
      nearest: AskNarenScenarioRef & {
        support_calls: number;
        /** 'thin' or 'solid'. A reading aid, NOT a gate — nothing declines on it, and
         *  ADR 0005 rules out a real threshold here. The raw count sits beside it. */
        evidence: 'thin' | 'solid';
      };
      citation: AskNarenCitation; match: AskNarenMatch };

/** Discriminated on `outcome`, NOT on a boolean. Two discriminators for one decision is how
 *  the answered and declined render paths eventually disagree about which one a response
 *  is; one key keeps `npm run build` exhaustive over all three. */
export type AskNarenResponse =
  | AskNarenAnswer
  | AskNarenDecline
  | AskNarenClarify
  | AskNarenRendered;
