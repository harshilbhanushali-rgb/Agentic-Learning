/**
 * The thread a CSM's conversation with Ask Naren is held in (issues #15, #46).
 *
 * THE CALLER HOLDS THE THREAD, NOT THE SERVICE. Ask Naren reads Postgres once at startup and
 * closes the connection before serving a single request, so it has nowhere to put a
 * conversation and no handle to put it with. The caller keeps it and replays it with every
 * message. Since #46 the caller is the proxy ROUTE, not the page: the route loads the stored
 * turns (`src/server/threads.ts`), derives the wire turns below with `turnFrom`, trims them
 * and forwards them. The browser never sends a thread, so nothing a page holds can reach the
 * service's prompt. The `localStorage` thread this used to be is retired; only its keys are
 * still cleared on sign-out (`clearLegacyThreads`).
 *
 * STORED SHAPE AND WIRE SHAPE STAY APART (#37). Storage keeps the full response verbatim;
 * the reduced turn here is DERIVED from it at read time and never stored.
 *
 * WHAT A TURN CARRIES. What the CSM typed, what Ask Naren said back, and the IDENTIFIERS of
 * the exchange the answer rested on — a scenario key, a `pair_id`, a call filename. Not the
 * response body replayed whole. ADR 0006's corollary is the reason: history may supply an
 * identifier, never text that gets embedded. The identifier lets a follow-up ground on the
 * exchange already cited without re-searching, because the service looks the text up in the
 * pool it already holds.
 *
 * The shape here mirrors `Brain/ask_naren/threads.py::ThreadTurn` exactly. That module
 * validates it with pydantic and REJECTS a thread it cannot parse, so a mismatch is a 400
 * rather than a silently ignored field.
 */
import type { AskNarenRendered, AskNarenResponse } from '@/types';
import type { StoredThread, StoredTurn, ThreadSummary } from '@/server/threads';

export interface ThreadTurn {
  /** What the CSM typed. Emptied, never removed, when `trimThread` elides a turn. */
  message: string;
  outcome: AskNarenResponse['outcome'];
  /** What Ask Naren said back: the answer, the clarify's question, or the decline's
   *  message. One field rather than three — `outcome` already says which it is. */
  reply: string;
  scenario_key: string;
  pair_id: number | null;
  call_filename: string;
}

/** Where the retired browser-held thread used to live (issues #15, #44): one key per user,
 *  plus the unsuffixed one from before sign-in. Never read or written any more (#46 moved
 *  threads to the server, with no migration); kept only so sign-out can clear what an older
 *  deploy left behind on a shared machine. */
const LEGACY_STORAGE_PREFIX = 'cs-ask-naren-thread-v1';

/**
 * The transport budget, in bytes of JSON.
 *
 * The service refuses a body over 64KB (`service.MAX_BODY_BYTES`), and a thread grows with
 * every message — so without a trim here a long enough conversation makes the tool return
 * 400 forever, and clearing it is not something a CSM can be asked to do. This is a smaller
 * number than the cap so the current message and the JSON scaffolding still fit. Applied by
 * the proxy route to the thread it rebuilds from storage.
 *
 * A SECOND, TIGHTER TRIM RUNS SERVER-SIDE (`threads.MAX_THREAD_CHARS`, 24k characters) and
 * is the authoritative one. Two rules with two jobs: this one makes the request FIT, that
 * one bounds what a thread contributes to a PROMPT. Both elide prose and keep identifiers,
 * so neither can strand a conversation.
 */
const BUDGET_BYTES = 48 * 1024;

/** Prose kept for as long as possible when trimming: the last turn is the one a follow-up
 *  is actually about. Matches `threads.KEEP_RECENT`. */
const KEEP_RECENT = 2;

/** Records one completed exchange, ready to be replayed with the next message.
 *
 *  The identifiers come off an ANSWERED or RENDERED response, because those are the
 *  responses that are about something. A clarify and a decline carry the conversation
 *  forward but rest on nothing, so they contribute no identifier to inherit. */
export function turnFrom(message: string, result: AskNarenResponse): ThreadTurn {
  const base = { message, outcome: result.outcome };
  switch (result.outcome) {
    case 'answered':
      return {
        ...base,
        reply: result.answer,
        scenario_key: result.citation.scenario_key,
        // NULL ON A LAYER C ANSWER (issue #17), which rests on a playbook evidence quote
        // rather than on a `kb_pairs` row. The consequence is deliberate and correct: a
        // follow-up needs a carried `pair_id` to ground on, so following up on a Layer C
        // answer finds none and the message is answered as a fresh question instead. That
        // is the honest degradation — the alternative is grounding a follow-up in whatever
        // exchange happened to be cited earlier, about a different thing.
        pair_id: result.citation.pair_id ?? null,
        call_filename: result.citation.call_filename,
      };
    case 'clarify':
      // The question is kept verbatim because "the same clarify is never asked twice"
      // (issue #16) is decided against exactly this text.
      return { ...base, reply: result.question, scenario_key: '', pair_id: null, call_filename: '' };
    case 'declined':
      return { ...base, reply: result.message, scenario_key: '', pair_id: null, call_filename: '' };
    case 'rendered':
      // A rendered answer is a LIST or a verbatim exchange, not prose, so there is no reply
      // text to replay. The turn records that it happened and what it was about; a CSM
      // scrolling back sees their question and the kind of thing that came back.
      return { ...base, reply: RENDERED_REPLIES[result.kind], ...renderedAnchor(result) };
    default: {
      const unhandled: never = result;
      throw new Error(`unhandled outcome: ${JSON.stringify(unhandled)}`);
    }
  }
}

/**
 * The identifiers a rendered turn records: exactly the ones its response already carries
 * (issue #52, ADR 0013). They are what the NEXT message continues from -- after "what's the
 * play for X", "and how does he word it?" can only stay on X if this turn says X.
 *
 * A `pair_id` only where the response shows ONE exchange; a scenario wherever it is about
 * one scenario; nothing on the four kinds that are about many situations at once.
 *
 * This does NOT make a rendered turn a follow-up source. A follow-up generates prose
 * grounded in a source, and `carried_source` in Brain/ask_naren/threads.py reads that from
 * ANSWERED turns only. And no `call_filename`: the thread shown to intake prints "(grounded
 * in <call>)" for a turn that has one, and a rendered answer grounded nothing.
 */
function renderedAnchor(result: AskNarenRendered): Pick<ThreadTurn, 'scenario_key' | 'pair_id' | 'call_filename'> {
  const none = { scenario_key: '', pair_id: null, call_filename: '' };
  switch (result.kind) {
    case 'show_exchange':
    case 'what_happened_next':
      return { ...none, scenario_key: result.citation.scenario_key, pair_id: result.citation.pair_id ?? null };
    case 'sequence':
    case 'phrasing':
    case 'pitfalls':
    case 'scenario_check':
    case 'play_confidence':
    case 'improve_at_move':
      return { ...none, scenario_key: result.scenario_key };
    case 'coverage_check':
      return { ...none, scenario_key: result.nearest.scenario_key };
    case 'discovery':
    case 'frequency':
    case 'where_else_seen':
    case 'call_prep':
      return none;
    default: {
      const unhandled: never = result;
      throw new Error(`unhandled rendered kind: ${JSON.stringify(unhandled)}`);
    }
  }
}

/**
 * Fit a thread into the request body WITHOUT losing a carried identifier.
 *
 * DROPPING THE OLDEST MESSAGES IS THE WRONG RULE (ADR 0006): the message that established
 * the scenario is usually the first one, and every later turn inherits that identifier from
 * it. So the unit of trimming is a turn's PROSE, not the turn — the middle goes first
 * (oldest first), then the first turn's text, then the older of the recent ones. Identifiers
 * survive all of it. Same order as `threads.trim`.
 */
export function trimThread(turns: ThreadTurn[], budget = BUDGET_BYTES): ThreadTurn[] {
  const trimmed = [...turns];
  if (!trimmed.length || sizeOf(trimmed) <= budget) return trimmed;

  const elide = (i: number) => {
    trimmed[i] = { ...trimmed[i], message: '', reply: '' };
  };

  for (let i = 1; i < Math.max(1, trimmed.length - KEEP_RECENT); i++) {
    elide(i);
    if (sizeOf(trimmed) <= budget) return trimmed;
  }
  elide(0);
  if (sizeOf(trimmed) <= budget) return trimmed;
  for (let i = Math.max(1, trimmed.length - KEEP_RECENT); i < trimmed.length - 1; i++) {
    elide(i);
    if (sizeOf(trimmed) <= budget) return trimmed;
  }

  // The last turn is what a follow-up refers to, so its reply goes before its message does.
  const last = trimmed.length - 1;
  trimmed[last] = { ...trimmed[last], reply: '' };
  if (sizeOf(trimmed) <= budget) return trimmed;
  const room = budget - sizeOf(trimmed.slice(0, last)) - sizeOf([{ ...trimmed[last], message: '' }]);
  trimmed[last] = { ...trimmed[last], message: room > 0 ? trimmed[last].message.slice(0, room) : '' };
  if (sizeOf(trimmed) <= budget) return trimmed;

  // Identifiers alone do not fit — hundreds of turns deep, and unreachable in practice. The
  // newest carried identifier is the live one, so the oldest go.
  while (trimmed.length > 1 && sizeOf(trimmed) > budget) trimmed.shift();
  return trimmed;
}

function sizeOf(turns: ThreadTurn[]): number {
  return new Blob([JSON.stringify(turns)]).size;
}

/**
 * A scenario key as something a CSM can read — `performance_pushback` → "performance
 * pushback".
 *
 * WHY AN ANSWER NAMES ITS SCENARIO AT ALL (issue #16). A thread carries a scenario
 * identifier forward, and if a CSM moves to a new situation without saying so, an inherited
 * one makes every later answer quietly about the wrong thing. There is no way to detect
 * that server-side — the answer is grounded and internally consistent, just about the wrong
 * client. Printing the scenario is what lets the person who knows catch it (ADR 0006, "a
 * carried identifier can strand").
 *
 * It also matters where nothing was carried: `application_volume_and_prioritization` holds
 * 11.8% of coachable pairs and 16% of what routes there is about jobs rather than
 * applications, so a catch-all scenario is worth naming even on a first message.
 */
export function scenarioLabel(key: string): string {
  return key.replace(/_/g, ' ');
}

/**
 * The scenario the NEXT question would carry forward: the newest turn whose wire turn names
 * one. Read through `turnFrom` on purpose rather than off the response, because what the
 * service inherits is exactly what `turnFrom` carries -- a scenario a decline or a
 * many-situation rendered answer mentions is not carried, and naming it here would misreport
 * the risk (#39: "a stale carried scenario is the known wrong-answer risk, so it has to be
 * visible").
 */
export function carriedScenario(turns: { question: string; response: AskNarenResponse }[]): string {
  // The same turn the service continues from (`threads.last_answer`, issue #53): the newest
  // answered or rendered one, never further back. Clarifies and declines rest on nothing.
  for (let i = turns.length - 1; i >= 0; i--) {
    const { outcome } = turns[i].response;
    if (outcome === 'answered' || outcome === 'rendered') {
      return turnFrom(turns[i].question, turns[i].response).scenario_key;
    }
  }
  return '';
}

/** Signing out leaves nothing of the retired browser-held thread behind -- every user's and
 *  the pre-sign-in one. Threads live on the server since #46, so this only ever clears what
 *  an older deploy wrote; it goes when nobody can still have those keys. */
export function clearLegacyThreads(): void {
  if (typeof window === 'undefined') return;
  try {
    for (let i = window.localStorage.length - 1; i >= 0; i--) {
      const key = window.localStorage.key(i);
      if (key?.startsWith(LEGACY_STORAGE_PREFIX)) window.localStorage.removeItem(key);
    }
  } catch {
    // Storage unavailable: there is nothing in it to clear.
  }
}

/* -- The thread APIs' JSON (issue #46) ------------------------------------------------------
 * What `/api/ask-naren/threads` and `/api/ask-naren/threads/[id]` send, and what the page
 * receives as its initial rail. Dates travel as ISO strings -- JSON has no date type, and a
 * server component's props are serialised the same way. Frontend-internal: the service never
 * sees these; the `response` inside a turn is the service's own contract, verbatim. */

export interface ThreadSummaryJson {
  id: number;
  title: string;
  renamed: boolean;
  createdAt: string;
  lastTurnAt: string;
  turnCount: number;
}

export interface StoredTurnJson {
  position: number;
  question: string;
  response: AskNarenResponse;
  askedAt: string;
  answeredAt: string;
}

export interface StoredThreadJson extends ThreadSummaryJson {
  turns: StoredTurnJson[];
}

export function summaryJson(s: ThreadSummary): ThreadSummaryJson {
  return {
    id: s.id,
    title: s.title,
    renamed: s.renamed,
    createdAt: s.createdAt.toISOString(),
    lastTurnAt: s.lastTurnAt.toISOString(),
    turnCount: s.turnCount,
  };
}

function turnJson(t: StoredTurn): StoredTurnJson {
  return {
    position: t.position,
    question: t.question,
    response: t.response,
    askedAt: t.askedAt.toISOString(),
    answeredAt: t.answeredAt.toISOString(),
  };
}

export function threadJson(t: StoredThread): StoredThreadJson {
  return { ...summaryJson(t), turns: t.turns.map(turnJson) };
}

/** What a rendered answer looks like when replayed as a past turn. The rendered payload is
 *  a list or a verbatim exchange rather than prose, so the thread records what KIND of thing
 *  came back rather than pretending to summarise it. */
const RENDERED_REPLIES: Record<AskNarenRendered['kind'], string> = {
  discovery: 'Showed what Ask Naren covers.',
  frequency: 'Showed which situations come up most.',
  show_exchange: 'Showed the real exchange.',
  what_happened_next: 'Showed how that conversation continued.',
  coverage_check: 'Reported what is covered near that situation.',
  sequence: 'Showed the order Naren runs it in.',
  phrasing: 'Showed how Naren words it.',
  pitfalls: 'Showed what usually goes wrong.',
  scenario_check: 'Showed when that play applies.',
  play_confidence: 'Showed how well evidenced that play is.',
  where_else_seen: 'Listed which accounts that has come up with.',
  call_prep: 'Laid out what is likely to come up on that call.',
  improve_at_move: 'Showed the criterion, the pitfalls and Naren doing it.',
};
