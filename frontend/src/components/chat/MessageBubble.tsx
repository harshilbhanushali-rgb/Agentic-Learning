'use client';

import type { ChatMessage } from '@/types';
import { CitationChip } from './CitationChip';
import { RetrievalTrace } from './RetrievalTrace';

/* Renders one turn. Oracle turns are full-width prose rather than bubbles —
 * these are cited, multi-paragraph answers people read, not chat banter. */

function Paragraphs({ text }: { text: string }) {
  return (
    <>
      {text.split('\n\n').map((para, i) => (
        <p key={i} className="text-sm text-ink leading-relaxed whitespace-pre-wrap [&:not(:last-child)]:mb-3">
          {para}
        </p>
      ))}
    </>
  );
}

/** Blinking block that trails streaming text. */
function Cursor() {
  return (
    <span
      aria-hidden="true"
      className="inline-block w-[2px] h-[1em] -mb-[0.15em] ml-0.5 bg-primary animate-pulse"
    />
  );
}

function ThinkingDots() {
  return (
    <span className="inline-flex gap-1 items-center" aria-label="Thinking">
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-ink-placeholder animate-pulse"
          style={{ animationDelay: `${i * 160}ms` }}
        />
      ))}
    </span>
  );
}

export function MessageBubble({
  message, onRetry,
}: { message: ChatMessage; onRetry: () => void }) {
  const streaming = message.status === 'streaming';

  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg rounded-br-sm bg-primary px-4 py-2.5">
          <p className="text-sm text-white leading-base whitespace-pre-wrap">{message.text}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div
        className="w-6 h-6 rounded-full bg-primary-surface text-primary shrink-0 mt-0.5
                   grid place-items-center text-[10px] font-bold tracking-tight"
        aria-hidden="true"
      >
        O
      </div>

      <div className="min-w-0 flex-1">
        <RetrievalTrace sources={message.retrieval} live={streaming} />

        {message.text ? (
          <div>
            <Paragraphs text={message.text} />
            {streaming && <Cursor />}
          </div>
        ) : (
          streaming && message.retrieval.length === 0 && <ThinkingDots />
        )}

        {message.status === 'error' && message.error && (
          <div
            role="alert"
            className="mt-3 flex items-start gap-3 rounded-md border border-error/30 bg-error-surface px-3 py-2.5"
          >
            <div className="flex-1 min-w-0">
              <p className="text-xs text-error font-medium">{message.error.message}</p>
              {message.text && (
                <p className="text-[11px] text-ink-2 mt-0.5">The partial answer above is kept.</p>
              )}
            </div>
            {message.error.retryable && (
              <button
                type="button"
                onClick={onRetry}
                className="text-xs font-medium text-primary hover:text-primary-hover shrink-0
                           underline underline-offset-2"
              >
                Try again
              </button>
            )}
          </div>
        )}

        {message.citations.length > 0 && (
          <div className="mt-4">
            <div className="text-[10px] uppercase tracking-[0.06em] text-ink-placeholder font-medium mb-2">
              Grounded in
            </div>
            <ul className="flex flex-col gap-1.5">
              {message.citations.map((c, i) => (
                <CitationChip key={c.id} citation={c} index={i} />
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
