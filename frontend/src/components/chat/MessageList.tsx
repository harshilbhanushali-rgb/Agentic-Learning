'use client';

import { useEffect, useRef } from 'react';
import type { ChatMessage } from '@/types';
import { MessageBubble } from './MessageBubble';

/* Follows the stream, but stops following the moment the reader scrolls up —
 * yanking someone back to the bottom while they are re-reading a citation is
 * the most irritating thing a chat UI can do. */

const NEAR_BOTTOM_PX = 80;

export function MessageList({
  messages, onRetry,
}: { messages: ChatMessage[]; onRetry: () => void }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  const lastText = messages[messages.length - 1]?.text ?? '';

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !stick.current) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, lastText]);

  return (
    <div
      ref={scrollRef}
      onScroll={e => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
      }}
      className="flex-1 overflow-y-auto px-6 py-8"
      role="log"
      aria-live="polite"
      aria-label="Conversation"
    >
      <div className="max-w-content mx-auto flex flex-col gap-8">
        {messages.map(m => (
          <MessageBubble key={m.id} message={m} onRetry={onRetry} />
        ))}
      </div>
    </div>
  );
}
