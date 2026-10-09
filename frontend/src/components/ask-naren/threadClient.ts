/**
 * The page's side of the Ask Naren routes (#46): each call's outcome as a value the page
 * switches on, so every status the routes can return has exactly one meaning here.
 *
 *   401 -> signed out: stash the draft and sign in (ADR 0011).
 *   404 -> the thread is not there any more (removed in another tab, or never yours).
 *   500 `store_unavailable`, any other failure, or no response at all -> the store is
 *        unreachable just now: a fault on our side, not about the question.
 */
import type { AskNarenDecline, AskNarenResponse } from '@/types';
import type { StoredThreadJson, ThreadSummaryJson } from '@/lib/thread';

export type Refusal = { kind: 'signed_out' } | { kind: 'not_found' } | { kind: 'unavailable' };
export type Result<T> = { kind: 'ok'; value: T } | Refusal;

async function call<T>(url: string, init: RequestInit, pick: (json: unknown) => T): Promise<Result<T>> {
  try {
    const res = await fetch(url, { cache: 'no-store', ...init });
    if (res.status === 401) return { kind: 'signed_out' };
    if (res.status === 404) return { kind: 'not_found' };
    if (!res.ok) return { kind: 'unavailable' };
    return { kind: 'ok', value: pick(await res.json()) };
  } catch {
    return { kind: 'unavailable' };
  }
}

const JSON_BODY = { 'Content-Type': 'application/json' };

export const fetchThreads = () =>
  call('/api/ask-naren/threads', {}, j => (j as { threads: ThreadSummaryJson[] }).threads);

export const fetchThread = (id: number) =>
  call(`/api/ask-naren/threads/${id}`, {}, j => (j as { thread: StoredThreadJson }).thread);

export const renameThread = (id: number, title: string | null) =>
  call(
    `/api/ask-naren/threads/${id}`,
    { method: 'PATCH', headers: JSON_BODY, body: JSON.stringify({ title }) },
    j => (j as { thread: ThreadSummaryJson }).thread,
  );

export const removeThread = (id: number) =>
  call(`/api/ask-naren/threads/${id}`, { method: 'DELETE' }, () => true);

/* -- Asking --------------------------------------------------------------------------- */

/** The last resort for the proxy ITSELF being gone -- the app is down, not the service. A
 *  bug rather than an expected path, but still not a reason to show a CSM a broken page. */
export const UNREACHABLE: AskNarenDecline = {
  outcome: 'declined',
  reason: 'service_unreachable',
  message:
    'Ask Naren could not be reached just now. Nothing was answered — this is a fault on ' +
    'our side, not a "no close match". Try again in a moment.',
};

/** The `outcome` values the service can send. Guards against a body that parsed as JSON but
 *  is not this contract -- a proxy or a crashed worker returning something else. */
const OUTCOMES = new Set<string>(['answered', 'declined', 'clarify', 'rendered']);

export type AskResult =
  | { kind: 'signed_out' }
  | { kind: 'thread_not_found' }
  /** Nothing was asked and nothing was stored: the store could not be read (#40), or the
   *  proxy itself did not answer. The question goes back in the box. */
  | { kind: 'not_asked'; result: AskNarenDecline }
  /** The service's response. `threadId`/`position` when the turn was recorded; `recorded:
   *  false` when the answer is real but is not in any thread (#40). */
  | { kind: 'answered'; result: AskNarenResponse; recorded: true; threadId: number; position: number }
  | { kind: 'answered'; result: AskNarenResponse; recorded: false };

export async function ask(situation: string, threadId: number | null): Promise<AskResult> {
  let res: Response;
  let body: unknown;
  try {
    res = await fetch('/api/ask-naren', {
      method: 'POST',
      headers: JSON_BODY,
      // The thread itself is NOT sent: the route rebuilds it from storage (#46).
      body: JSON.stringify({ situation, thread_id: threadId }),
    });
    // THE ONE STATUS THAT IS THE SIGNAL. A 401 is the proxy saying the session has ended,
    // which is not an answer and not a decline: nothing was asked of the service.
    if (res.status === 401) return { kind: 'signed_out' };
    body = await res.json();
  } catch {
    return { kind: 'not_asked', result: UNREACHABLE };
  }

  const b = body as { outcome?: unknown; reason?: unknown; error?: unknown } | null;
  if (res.status === 404 && b?.error === 'thread_not_found') return { kind: 'thread_not_found' };
  if (!b || typeof b.outcome !== 'string' || !OUTCOMES.has(b.outcome)) {
    return { kind: 'not_asked', result: UNREACHABLE };
  }
  if (b.outcome === 'declined' && b.reason === 'store_unavailable') {
    return { kind: 'not_asked', result: body as AskNarenDecline };
  }

  // Any other status still carries the contract: the service's own fault is a 503 with a
  // decline body, a busy refusal a 429, and so is the proxy's unreachable response.
  const result = body as AskNarenResponse;
  const thread = Number(res.headers.get('X-Ask-Naren-Thread'));
  const position = Number(res.headers.get('X-Ask-Naren-Position'));
  if (res.headers.get('X-Ask-Naren-Recorded') !== 'false' && thread > 0 && position > 0) {
    return { kind: 'answered', result, recorded: true, threadId: thread, position };
  }
  return { kind: 'answered', result, recorded: false };
}
