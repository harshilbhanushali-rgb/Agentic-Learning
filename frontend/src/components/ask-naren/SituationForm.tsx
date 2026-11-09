'use client';

import { useRef, useEffect } from 'react';

import { PRODUCT_NAME } from '@/components/ask-naren/N10Mark';

/**
 * The one input, as a chat composer pinned under the conversation.
 *
 * ENTER SENDS, SHIFT+ENTER STARTS A NEW LINE -- the chat convention CSMs already have in their
 * hands (operator's call, 2026-10-10). It replaced Ctrl+Enter, which guarded a half-typed
 * situation against a stray Enter; that protection is traded for not surprising anyone.
 *
 * A textarea rather than a single-line field because a situation is a few sentences of
 * context. It grows with what is typed, up to a cap, so a long paste stays readable without
 * pushing the conversation off screen.
 */
export function SituationForm({
  value,
  onChange,
  onSubmit,
  busy,
  large = false,
}: {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  busy: boolean;
  /** The empty page's centred box: taller, with the first-question prompt. */
  large?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // Focused on mount so the page is usable without a click -- this screen has exactly one
  // thing to do on arrival.
  useEffect(() => { ref.current?.focus(); }, []);

  // Grow with the text, up to the CSS max-height, then scroll inside.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  const canSubmit = value.trim().length > 0 && !busy;

  return (
    <form
      className="flex w-full flex-col gap-2"
      onSubmit={e => { e.preventDefault(); if (canSubmit) onSubmit(); }}
    >
      <label htmlFor="situation" className="sr-only">
        Your question
      </label>
      <div
        className={`flex items-end gap-3 rounded-[22px] border border-line bg-bg shadow-ambient transition-colors duration-fast ease-out-quart focus-within:border-primary ${large ? 'px-5 pb-3 pt-4' : 'py-2.5 pl-5 pr-2.5'}`}
      >
        <textarea
          id="situation"
          ref={ref}
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (canSubmit) onSubmit();
            }
          }}
          rows={large ? 3 : 1}
          placeholder={large ? 'Ask me anything…' : 'Ask a follow-up…'}
          disabled={busy}
          className={`max-h-48 w-full resize-none bg-transparent py-1.5 leading-relaxed text-ink placeholder:text-ink-placeholder focus:outline-none disabled:opacity-60 ${large ? 'min-h-[80px] text-[17px]' : 'min-h-[24px] text-[15px]'}`}
        />
        <button
          type="submit"
          disabled={!canSubmit}
          aria-label={busy ? 'Asking…' : `Ask ${PRODUCT_NAME}`}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary text-white transition-colors duration-fast ease-out-quart hover:bg-primary-hover disabled:cursor-not-allowed disabled:bg-line disabled:text-ink-placeholder"
        >
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 19V5M5 12l7-7 7 7" />
          </svg>
        </button>
      </div>
      <span className="px-2 text-center text-[12px] text-ink-2">
        Enter to send, Shift+Enter for a new line &middot; Type{' '}
        <span className="font-semibold text-ink">/help</span> for what to ask
      </span>
    </form>
  );
}
