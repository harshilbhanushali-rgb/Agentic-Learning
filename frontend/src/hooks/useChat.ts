'use client';

/* Owns the chat conversation: message state, the streaming lifecycle,
 * cancellation and retry. Components stay presentational.
 *
 * Knows nothing about transport — it consumes StreamEvents from whichever
 * ApiClient is active, so it behaves identically against mock and live. */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getApiClient } from '@/lib/api';
import type { ChatMessage, ChatError } from '@/types';

let localId = 0;
const nextId = (p: string) => `${p}_local_${(localId += 1)}`;

const now = () => new Date().toISOString();

const userMessage = (text: string): ChatMessage => ({
  id: nextId('user'), role: 'user', text, status: 'complete',
  createdAt: now(), citations: [], retrieval: [],
});

const pendingOracleMessage = (): ChatMessage => ({
  id: nextId('oracle'), role: 'oracle', text: '', status: 'streaming',
  createdAt: now(), citations: [], retrieval: [],
});

export interface UseChat {
  messages: ChatMessage[];
  /** True from submit until the stream terminates. */
  isStreaming: boolean;
  /** Session bootstrap — distinct from isStreaming. */
  isReady: boolean;
  send: (text: string) => void;
  cancel: () => void;
  /** Re-sends the last user turn, discarding the failed reply. */
  retry: () => void;
  clear: () => void;
}

export function useChat(): UseChat {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isReady, setIsReady] = useState(false);

  const sessionId = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const lastPrompt = useRef<string>('');
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    getApiClient()
      .createSession()
      .then(s => { if (mounted.current) { sessionId.current = s.id; setIsReady(true); } })
      .catch(() => { if (mounted.current) setIsReady(true); });

    return () => {
      mounted.current = false;
      abortRef.current?.abort();
    };
  }, []);

  /** Applies a partial update to one message by id. */
  const patch = useCallback((id: string, fn: (m: ChatMessage) => ChatMessage) => {
    setMessages(prev => prev.map(m => (m.id === id ? fn(m) : m)));
  }, []);

  const run = useCallback(async (text: string) => {
    const reply = pendingOracleMessage();
    setMessages(prev => [...prev, reply]);
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    const fail = (error: ChatError) =>
      patch(reply.id, m => ({ ...m, status: 'error', error }));

    try {
      // A session is normally ready by now; fall back rather than block.
      const id = sessionId.current ?? 'pending';
      const stream = getApiClient().sendMessage({ sessionId: id, text, signal: controller.signal });

      for await (const ev of stream) {
        if (!mounted.current || controller.signal.aborted) break;

        switch (ev.type) {
          case 'retrieval':
            patch(reply.id, m => ({ ...m, retrieval: ev.sources }));
            break;
          case 'token':
            patch(reply.id, m => ({ ...m, text: m.text + ev.text }));
            break;
          case 'citation':
            patch(reply.id, m => ({ ...m, citations: [...m.citations, ev.citation] }));
            break;
          case 'done':
            patch(reply.id, m => ({ ...m, status: 'complete' }));
            break;
          case 'error':
            fail(ev.error);
            break;
        }
      }
    } catch (err) {
      if ((err as Error)?.name === 'AbortError') {
        // Cancelling keeps whatever streamed — it is still useful to read.
        patch(reply.id, m => ({ ...m, status: 'complete' }));
      } else {
        fail({
          code: 'server',
          message: err instanceof Error ? err.message : 'Something went wrong.',
          retryable: true,
        });
      }
    } finally {
      if (mounted.current) setIsStreaming(false);
      abortRef.current = null;
    }
  }, [patch]);

  const send = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed || isStreaming) return;
    lastPrompt.current = trimmed;
    setMessages(prev => [...prev, userMessage(trimmed)]);
    void run(trimmed);
  }, [isStreaming, run]);

  const cancel = useCallback(() => abortRef.current?.abort(), []);

  const retry = useCallback(() => {
    if (isStreaming || !lastPrompt.current) return;
    // Drop the failed reply, keep the question.
    setMessages(prev => {
      const last = prev[prev.length - 1];
      return last?.role === 'oracle' && last.status === 'error' ? prev.slice(0, -1) : prev;
    });
    void run(lastPrompt.current);
  }, [isStreaming, run]);

  const clear = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    lastPrompt.current = '';
  }, []);

  return { messages, isStreaming, isReady, send, cancel, retry, clear };
}
