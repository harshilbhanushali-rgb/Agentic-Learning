/**
 * The thread a CSM's conversation with Ask Naren is held in (issue #15).
 *
 * THE PAGE HOLDS THE THREAD, NOT THE SERVICE. Ask Naren reads Postgres once at startup and
 * closes the connection before serving a single request, so it has nowhere to put a
 * conversation and no handle to put it with. The caller keeps it and replays it with every
 * message. `localStorage` is the same pattern the app already uses for mode and theme.
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
 * rather than a silently ignored field — which is why `load` below validates what comes out
 * of storage instead of trusting it.
 */
import type { AskNarenResponse } from '@/types';

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

/** Where a thread lives between reloads. Versioned in the key itself: a shape change ships
 *  a new key rather than trying to migrate what is in a CSM's browser, and the old one is
 *  simply never read again.
 *
 *  ONE KEY, NOT ONE PER CSM. The `csm_id` dropdown is not built yet (issue #12 phase 0), so
 *  there is no identity to key on. Story 22 — "sharing a machine, I should not see somebody
 *  else's thread" — lands with the dropdown, and this key gains the CSM then. */
const STORAGE_KEY = 'cs-ask-naren-thread-v1';

/**
 * The transport budget, in bytes of JSON.
 *
 * The service refuses a body over 64KB (`service.MAX_BODY_BYTES`), and a thread grows with
 * every message — so without a trim here a long enough conversation makes the tool return
 * 400 forever, and clearing it is not something a CSM can be asked to do. This is a smaller
 * number than the cap so the current message and the JSON scaffolding still fit.
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
 *  The identifiers come off an ANSWERED response only, because they are the only responses
 *  that rest on anything. A clarify and a decline carry the conversation forward but ground
 *  nothing, so they contribute no identifier to inherit. */
export function turnFrom(message: string, result: AskNarenResponse): ThreadTurn {
  const base = { message, outcome: result.outcome };
  switch (result.outcome) {
    case 'answered':
      return {
        ...base,
        reply: result.answer,
        scenario_key: result.citation.scenario_key,
        pair_id: result.citation.pair_id,
        call_filename: result.citation.call_filename,
      };
    case 'clarify':
      // The question is kept verbatim because "the same clarify is never asked twice"
      // (issue #16) is decided against exactly this text.
      return { ...base, reply: result.question, scenario_key: '', pair_id: null, call_filename: '' };
    case 'declined':
      return { ...base, reply: result.message, scenario_key: '', pair_id: null, call_filename: '' };
    default: {
      const unhandled: never = result;
      throw new Error(`unhandled outcome: ${JSON.stringify(unhandled)}`);
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

/** What is in storage, or an empty thread.
 *
 *  VALIDATED, NOT TRUSTED. The service rejects a malformed thread with a 400 rather than
 *  ignoring it, so a stale shape left in a browser by an older deploy would break the tool
 *  for that CSM until they cleared their own storage. Anything that is not recognisably a
 *  thread is discarded here instead, which costs one conversation and never a working page.
 *
 *  Returns [] during SSR, where there is no `window` at all. */
export function load(): ThreadTurn[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed) || !parsed.every(isTurn)) return [];
    return parsed as ThreadTurn[];
  } catch {
    return [];
  }
}

export function save(turns: ThreadTurn[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(turns));
  } catch {
    // A full or disabled storage must not cost a CSM the answer on their screen. The thread
    // keeps working for this page load and simply does not survive a reload.
  }
}

const OUTCOMES: ReadonlySet<string> = new Set(['answered', 'declined', 'clarify']);

/** The same fields the service's pydantic turn requires, checked in the same strictness:
 *  an unrecognised outcome or a wrong-typed identifier means this is not our shape. */
function isTurn(value: unknown): value is ThreadTurn {
  if (typeof value !== 'object' || value === null) return false;
  const t = value as Record<string, unknown>;
  return (
    typeof t.message === 'string' &&
    typeof t.reply === 'string' &&
    typeof t.scenario_key === 'string' &&
    typeof t.call_filename === 'string' &&
    (t.pair_id === null || typeof t.pair_id === 'number') &&
    typeof t.outcome === 'string' &&
    OUTCOMES.has(t.outcome)
  );
}
