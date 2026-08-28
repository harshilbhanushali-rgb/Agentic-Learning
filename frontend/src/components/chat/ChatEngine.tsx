'use client';

import { useChat } from '@/hooks/useChat';
import { MessageList } from './MessageList';
import { Composer } from './Composer';
import { EmptyState } from './EmptyState';

/* Route-agnostic root for the chat experience.
 *
 * Deliberately owns NO page chrome — no min-height, no page padding, no
 * knowledge of routing. It fills whatever container it is given, so the same
 * component can back both the /chat page and the ⌘K panel in AppShell.
 * Keep it that way: the promotion to a panel is free only while this holds. */

export function ChatEngine() {
  const { messages, isStreaming, isReady, send, cancel, retry } = useChat();

  return (
    <div className="flex flex-col h-full min-h-0">
      {messages.length === 0
        ? <EmptyState onPick={send} />
        : <MessageList messages={messages} onRetry={retry} />}

      <Composer
        onSend={send}
        onCancel={cancel}
        isStreaming={isStreaming}
        disabled={!isReady}
      />
    </div>
  );
}
