'use client';

import { useEffect, useRef, useState } from 'react';

/* Enter sends, Shift+Enter newlines. Grows to a cap, then scrolls. */

const MAX_ROWS_PX = 160;

export function Composer({
  onSend, onCancel, isStreaming, disabled,
}: {
  onSend: (text: string) => void;
  onCancel: () => void;
  isStreaming: boolean;
  disabled: boolean;
}) {
  const [value, setValue] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);

  // Autosize.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, MAX_ROWS_PX)}px`;
  }, [value]);

  // Reclaim focus once a reply finishes — the next question usually follows.
  useEffect(() => {
    if (!isStreaming) ref.current?.focus();
  }, [isStreaming]);

  const submit = () => {
    const text = value.trim();
    if (!text || isStreaming || disabled) return;
    onSend(text);
    setValue('');
  };

  return (
    <div className="border-t border-line-subtle bg-bg px-6 py-4">
      <div className="max-w-content mx-auto">
        <div className="flex items-end gap-2 rounded-lg border border-line bg-surface px-3 py-2
                        focus-within:border-primary transition-colors duration-fast">
          <textarea
            ref={ref}
            rows={1}
            value={value}
            disabled={disabled}
            onChange={e => setValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
            }}
            placeholder={disabled ? 'Connecting…' : 'Ask anything — ROI benchmarks, objection handles, client history…'}
            aria-label="Ask the Oracle"
            className="flex-1 resize-none bg-transparent text-sm text-ink placeholder:text-ink-placeholder
                       leading-base outline-none py-1 disabled:cursor-not-allowed"
          />

          {isStreaming ? (
            <button
              type="button"
              onClick={onCancel}
              className="shrink-0 text-xs font-medium px-3 py-1.5 rounded-md border border-line
                         text-ink-2 hover:bg-surface-raised transition-colors duration-fast"
            >
              Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!value.trim() || disabled}
              className="shrink-0 text-xs font-medium px-3 py-1.5 rounded-md bg-primary text-white
                         hover:bg-primary-hover disabled:opacity-40 disabled:cursor-not-allowed
                         transition-colors duration-fast"
            >
              Ask
            </button>
          )}
        </div>

        <p className="text-[10px] text-ink-placeholder mt-2 px-1">
          Enter to send · Shift+Enter for a new line
        </p>
      </div>
    </div>
  );
}
