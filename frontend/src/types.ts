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
  pair_id: number;
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
  match: AskNarenMatch;
}

/** Where each one comes from, because they must stay distinguishable to whoever is
 *  debugging (issue #6): `no_close_match` and `grounding_unverified` are the answerer
 *  deciding it cannot ground an answer -- the tool working correctly. `service_error` is the
 *  service's own 503, raised when answering threw. `service_unreachable` is synthesised by
 *  the proxy when the service could not be reached or timed out at all.
 *
 *  The last two are faults; the first two are not. Rendering them identically to a CSM is
 *  deliberate, but COLLAPSING them would hide an outage behind what looks like normal
 *  conservative behaviour, so the reason codes stay distinct all the way through. */
export type AskNarenDeclineReason =
  | 'no_close_match'
  | 'grounding_unverified'
  /** Decided by intake BEFORE anything is searched (issue #14): the question wants a fact
   *  about Joveo's product, pricing or contracts, which is not what Naren's call
   *  transcripts contain. Distinct from the two above because rewording cannot help — which
   *  is exactly why it is a decline and not a clarify. Carries no `match`: nothing was
   *  searched, so there is no cosine to report. */
  | 'out_of_scope'
  | 'service_error'
  | 'service_unreachable';

export interface AskNarenDecline {
  outcome: 'declined';
  intake?: AskNarenIntake;
  reason: AskNarenDeclineReason;
  /** Already written for a CSM to read. Render it as-is; do not compose a message from
   *  `reason` in the frontend, or there are two sources of truth for the same sentence. */
  message: string;
  match?: AskNarenMatch;
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

/** Discriminated on `outcome`, NOT on a boolean. Two discriminators for one decision is how
 *  the answered and declined render paths eventually disagree about which one a response
 *  is; one key keeps `npm run build` exhaustive over all three. */
export type AskNarenResponse = AskNarenAnswer | AskNarenDecline | AskNarenClarify;
