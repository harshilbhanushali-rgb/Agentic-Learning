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
 * Discriminated on `declined`, which is what makes the two render paths exhaustive: an
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
   *  shipped path, where the shortlist is one exchange long (see ADR 0003). */
  rank: number;
}

export interface AskNarenAnswer {
  declined: false;
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
  | 'service_error'
  | 'service_unreachable';

export interface AskNarenDecline {
  declined: true;
  reason: AskNarenDeclineReason;
  /** Already written for a CSM to read. Render it as-is; do not compose a message from
   *  `reason` in the frontend, or there are two sources of truth for the same sentence. */
  message: string;
  match?: AskNarenMatch;
}

export type AskNarenResponse = AskNarenAnswer | AskNarenDecline;
