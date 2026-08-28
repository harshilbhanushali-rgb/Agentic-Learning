/* Mock implementation of ApiClient.
 *
 * Deliberately imperfect: it is slow, it streams token-by-token, and it can
 * be made to fail. A mock that returns instantly and always succeeds produces
 * a UI with no loading states and no error paths — those then have to be
 * retrofitted into finished components the day a real server appears.
 *
 * Tune from the browser console:
 *   __oracle.latency = 1200   // ms before first byte
 *   __oracle.fail    = true   // next send errors mid-stream
 *   __oracle.speed   = 8      // ms between tokens
 */

import type { ApiClient, SendMessageArgs } from './types';
import type {
  ChatMessage, ChatSession, StreamEvent, Citation, RetrievalSource, Mode,
} from '@/types';
import { EGO_TRAPS, RADAR_MEETINGS, TEST_QUEUE, KNOWLEDGE_DROPS,
         NEWBIE_RADAR_MEETINGS, NEWBIE_TEST_QUEUE } from '@/data/workspace';

/* ── tunables ──────────────────────────────────────────────── */

interface OracleKnobs { latency: number; speed: number; fail: boolean }

const knobs: OracleKnobs = { latency: 700, speed: 12, fail: false };

if (typeof window !== 'undefined') {
  (window as unknown as { __oracle: OracleKnobs }).__oracle = knobs;
}

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'));
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(t);
      reject(new DOMException('Aborted', 'AbortError'));
    }, { once: true });
  });

let seq = 0;
const uid = (p: string) => `${p}_${(seq += 1).toString(36)}`;

/* ── canned answers ────────────────────────────────────────── */

interface Answer {
  match: RegExp;
  retrieval: RetrievalSource[];
  body: string;
  citations: Citation[];
}

const ANSWERS: Answer[] = [
  {
    match: /qbr|opening|skeptic|cxo/i,
    retrieval: [
      { id: 'r1', label: 'QBR Mastery',           kind: 'module',      matches: 4 },
      { id: 'r2', label: 'Failure Library',       kind: 'failure',     matches: 2 },
      { id: 'r3', label: 'Account A · transcript', kind: 'transcript', matches: 6 },
    ],
    body:
      "Open with their scorecard, not yours.\n\n" +
      "A skeptical CXO has already decided the meeting is a sales pitch. The fastest way " +
      "to break that frame is to spend the first three minutes on numbers they gave you — " +
      "their targets, their board metrics, their language. You earn the right to show your " +
      "data by proving you understood theirs first.\n\n" +
      "Three things to avoid, drawn from calls that went badly:\n\n" +
      "• Don't lead with platform metrics. Impressions and CPC read as vanity to a CFO.\n" +
      "• Don't give ROI as a range. Ranges signal uncertainty and invite pushback.\n" +
      "• Don't defend the last quarter before they've criticised it. Naming the risk first " +
      "is disarming; pre-defending is not.\n\n" +
      "If the room goes quiet after your opening, that's usually good — let it sit.",
    citations: [
      { id: 'c1', label: 'QBR Mastery · Module 2 · §1.1', kind: 'module',
        excerpt: "Their frame first: the opening three minutes belong to the client's own numbers." },
      { id: 'c2', label: 'Failure Library · Novo Nordisk · Ch 2', kind: 'failure',
        excerpt: 'The CFO asked about ROI timeline — a range was given. Ranges signal uncertainty.' },
      { id: 'c3', label: 'Living Case Study · Account A · Ch 4', kind: 'case-study',
        excerpt: 'Named the risk before the client did — pre-emption, not pre-defence.' },
    ],
  },
  {
    match: /roi|benchmark|cph|cost per/i,
    retrieval: [
      { id: 'r1', label: 'Benchmarks library',  kind: 'module',  matches: 5 },
      { id: 'r2', label: 'FMCG Renewal Playbook', kind: 'module', matches: 3 },
    ],
    body:
      "Reframe CPH into brand ROI before you quote a number.\n\n" +
      "Cost-per-hire invites line-item comparison against the cheapest job board on the " +
      "market, and you will lose that comparison every time. The stronger move is to shift " +
      "the denominator: quality-of-hire, time-to-productivity, and 90-day retention.\n\n" +
      "When you do quote benchmarks, quote a single anchored figure with the cohort attached " +
      "— 'for FMCG accounts of your headcount, median is 38 days' — not a range.",
    citations: [
      { id: 'c1', label: 'FMCG Renewal Playbook · Module 6 · §3.1', kind: 'module',
        excerpt: 'Shift the denominator: quality-of-hire over cost-per-hire.' },
      { id: 'c2', label: 'Benchmarks · FMCG · APAC', kind: 'module' },
    ],
  },
  {
    match: /internal tool|build.*ourselves|in-house|objection/i,
    retrieval: [
      { id: 'r1', label: 'Objection handling',   kind: 'module',  matches: 4 },
      { id: 'r2', label: 'Project Atlas · post-mortem', kind: 'failure', matches: 2 },
    ],
    body:
      "\"We have internal tools\" is almost never about the tools.\n\n" +
      "It's a budget-ownership signal — someone internally has staked their credibility on " +
      "the in-house build. Attacking the tool attacks that person, usually while they're in " +
      "the room.\n\n" +
      "Ask what the internal build is *already* doing well, and find the seam it doesn't " +
      "cover. Project Atlas was lost by arguing feature parity for two quarters against a " +
      "team that only needed one workflow the internal tool couldn't reach.",
    citations: [
      { id: 'c1', label: 'Failure Library · Project Atlas · Ch 1', kind: 'failure',
        excerpt: 'Two quarters spent arguing feature parity. The gap was one unserved workflow.' },
      { id: 'c2', label: 'Objection Handling · Module 3 · §2', kind: 'module' },
    ],
  },
];

const FALLBACK: Answer = {
  match: /.*/,
  retrieval: [
    { id: 'r1', label: 'Institutional memory', kind: 'transcript', matches: 3 },
  ],
  body:
    "I don't have a grounded answer for that yet.\n\n" +
    "This is mock data — the Oracle is wired end-to-end but not yet connected to the Brain. " +
    "Try asking about QBR openings, ROI benchmarks, or the \"we have internal tools\" objection " +
    "to see a fully cited response.",
  citations: [],
};

const pick = (q: string) => ANSWERS.find(a => a.match.test(q)) ?? FALLBACK;

/** Split into tokens that look like an LLM's — words, keeping whitespace. */
const tokenize = (s: string) => s.match(/\s*\S+/g) ?? [];

/* ── the adapter ───────────────────────────────────────────── */

export const mockClient: ApiClient = {
  async getEgoTraps(mode: Mode) {
    await wait(knobs.latency);
    return mode === 'newbie' ? [] : EGO_TRAPS;
  },
  async getRadar(mode: Mode) {
    await wait(knobs.latency);
    return mode === 'newbie' ? NEWBIE_RADAR_MEETINGS : RADAR_MEETINGS;
  },
  async getTestQueue(mode: Mode) {
    await wait(knobs.latency);
    return mode === 'newbie' ? NEWBIE_TEST_QUEUE : TEST_QUEUE;
  },
  async getKnowledgeDrops() {
    await wait(knobs.latency);
    return KNOWLEDGE_DROPS;
  },

  async listSessions() {
    await wait(knobs.latency / 2);
    return [];
  },

  async createSession(): Promise<ChatSession> {
    await wait(120);
    const now = new Date().toISOString();
    return { id: uid('sess'), title: 'New conversation', createdAt: now, updatedAt: now, messageCount: 0 };
  },

  async getMessages(): Promise<ChatMessage[]> {
    await wait(knobs.latency / 2);
    return [];
  },

  async *sendMessage({ text, signal }: SendMessageArgs): AsyncIterable<StreamEvent> {
    const answer = pick(text);

    // Thinking pause before anything comes back.
    await wait(knobs.latency, signal);
    yield { type: 'retrieval', sources: answer.retrieval };

    // Retrieval reads as work being done, so give it a beat.
    await wait(420, signal);

    const tokens = tokenize(answer.body);
    for (let i = 0; i < tokens.length; i += 1) {
      if (knobs.fail && i === Math.floor(tokens.length / 3)) {
        knobs.fail = false;
        yield { type: 'error', error: {
          code: 'network',
          message: 'Lost connection to the Oracle.',
          retryable: true,
        }};
        return;
      }
      await wait(knobs.speed, signal);
      yield { type: 'token', text: tokens[i] };
    }

    for (const citation of answer.citations) {
      await wait(90, signal);
      yield { type: 'citation', citation };
    }

    yield { type: 'done', messageId: uid('msg') };
  },
};
