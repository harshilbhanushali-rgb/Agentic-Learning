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

/* ── Chat / Knowledge Oracle ───────────────────────────────── */

/** A grounding reference. `label` follows the app-wide source convention,
 *  e.g. 'QBR Mastery · Module 2 · §1.1'. */
export interface Citation {
  id: string;
  label: string;
  kind: 'module' | 'case-study' | 'failure' | 'transcript' | 'account';
  /** Optional in-app destination, when the cited artefact has a page. */
  href?: string;
  /** Verbatim supporting passage, shown on expand. */
  excerpt?: string;
}

/** One knowledge source the Oracle consulted, surfaced while it thinks.
 *  Design Principle 5 — show the work. */
export interface RetrievalSource {
  id: string;
  label: string;
  kind: Citation['kind'];
  matches: number;
}

export type ChatRole = 'user' | 'oracle';

export type ChatMessageStatus = 'streaming' | 'complete' | 'error';

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  status: ChatMessageStatus;
  createdAt: string;
  /** Populated progressively for oracle turns. */
  citations: Citation[];
  retrieval: RetrievalSource[];
  error?: ChatError;
}

export interface ChatError {
  code: 'network' | 'timeout' | 'rate_limit' | 'server' | 'aborted';
  message: string;
  retryable: boolean;
}

export interface ChatSession {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
}

/** Wire protocol. The mock adapter and the eventual SSE transport emit
 *  exactly these — the UI never parses raw text. */
export type StreamEvent =
  | { type: 'retrieval'; sources: RetrievalSource[] }
  | { type: 'token'; text: string }
  | { type: 'citation'; citation: Citation }
  | { type: 'done'; messageId: string }
  | { type: 'error'; error: ChatError };
