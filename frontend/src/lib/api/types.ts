/* ═══════════════════════════════════════════════════════════════════
 * THE FRONTEND / BACKEND CONTRACT
 * ═══════════════════════════════════════════════════════════════════
 *
 * This file is the single boundary between the UI and the server.
 *
 *   Frontend owns:  this interface + `mock.ts`
 *   Backend  owns:  `http.ts` — a second implementation of ApiClient
 *
 * Rules that keep the two sides independent:
 *   1. Components NEVER import an adapter directly. They call hooks,
 *      hooks call `getApiClient()` from './index'.
 *   2. No `fetch` outside `http.ts`.
 *   3. Changing a signature here is a cross-team change — say so.
 *
 * Swap implementations with NEXT_PUBLIC_API_MODE=mock|live.
 * ═══════════════════════════════════════════════════════════════════ */

import type {
  EgoTrap,
  RadarMeeting,
  TestQueueItem,
  KnowledgeDrop,
  ChatSession,
  ChatMessage,
  StreamEvent,
  Mode,
} from '@/types';

export interface SendMessageArgs {
  sessionId: string;
  text: string;
  /** Aborts the stream when the user cancels or navigates away. */
  signal?: AbortSignal;
}

export interface ApiClient {
  /* ── Workspace ────────────────────────────────────────────── */
  getEgoTraps(mode: Mode): Promise<EgoTrap[]>;
  getRadar(mode: Mode): Promise<RadarMeeting[]>;
  getTestQueue(mode: Mode): Promise<TestQueueItem[]>;
  getKnowledgeDrops(): Promise<KnowledgeDrop[]>;

  /* ── Chat / Knowledge Oracle ──────────────────────────────── */
  listSessions(): Promise<ChatSession[]>;
  createSession(): Promise<ChatSession>;
  getMessages(sessionId: string): Promise<ChatMessage[]>;

  /**
   * Streams the Oracle's reply.
   *
   * MUST be incremental. The UI is built around progressive rendering —
   * an implementation that resolves everything at once will technically
   * satisfy the types and still produce a visibly broken experience.
   *
   * Expected event order:
   *   retrieval → token* → citation* → done
   * `error` may arrive at any point and terminates the stream.
   */
  sendMessage(args: SendMessageArgs): AsyncIterable<StreamEvent>;
}

export type ApiMode = 'mock' | 'live';
