/* ═══════════════════════════════════════════════════════════════════
 * BACKEND: THIS FILE IS YOURS.
 * ═══════════════════════════════════════════════════════════════════
 *
 * Implement `ApiClient` (see ./types.ts) against the FastAPI service.
 * Nothing else in the frontend needs to change — flip the env var:
 *
 *     NEXT_PUBLIC_API_MODE=live
 *     NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
 *
 * Every method below throws until implemented, so a half-finished
 * adapter fails loudly instead of rendering an empty screen.
 *
 * ── The one that matters ──────────────────────────────────────────
 *
 * `sendMessage` must stream. The UI renders tokens as they arrive and
 * shows retrieval sources before the first token. Buffering the whole
 * reply and yielding it once will type-check and still look broken.
 *
 * Suggested transport — SSE over POST:
 *
 *     POST /chat/sessions/{id}/messages
 *     Accept: text/event-stream
 *
 *     event: retrieval
 *     data: {"sources":[{"id":"r1","label":"QBR Mastery","kind":"module","matches":4}]}
 *
 *     event: token
 *     data: {"text":" Open"}
 *
 *     event: citation
 *     data: {"citation":{"id":"c1","label":"QBR Mastery · Module 2 · §1.1","kind":"module"}}
 *
 *     event: done
 *     data: {"messageId":"msg_123"}
 *
 * Note EventSource cannot POST — use fetch + ReadableStream, and honour
 * `args.signal` so cancelling a reply actually closes the connection.
 * ═══════════════════════════════════════════════════════════════════ */

import type { ApiClient } from './types';

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

const notImplemented = (method: string): never => {
  throw new Error(
    `[api/http] ${method}() is not implemented yet. ` +
    `Either implement it in src/lib/api/http.ts or run with NEXT_PUBLIC_API_MODE=mock.`,
  );
};

export const httpClient: ApiClient = {
  getEgoTraps:       () => notImplemented('getEgoTraps'),
  getRadar:          () => notImplemented('getRadar'),
  getTestQueue:      () => notImplemented('getTestQueue'),
  getKnowledgeDrops: () => notImplemented('getKnowledgeDrops'),
  listSessions:      () => notImplemented('listSessions'),
  createSession:     () => notImplemented('createSession'),
  getMessages:       () => notImplemented('getMessages'),
  // eslint-disable-next-line require-yield
  async *sendMessage() { notImplemented('sendMessage'); },
};
