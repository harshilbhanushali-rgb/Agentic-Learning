'use client';

import { useRef, useEffect } from 'react';

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
}: {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  busy: boolean;
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
      className="flex flex-col gap-1.5"
      onSubmit={e => { e.preventDefault(); if (canSubmit) onSubmit(); }}
    >
      <label htmlFor="situation" className="sr-only">
        The situation
      </label>
      <div className="flex items-end gap-2 rounded-2xl border border-line bg-bg px-4 py-2.5 shadow-sm transition-colors duration-fast ease-out-quart focus-within:border-primary">
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
          rows={1}
          placeholder="What did the client say, and what do you need to respond to?"
          disabled={busy}
          className="max-h-48 min-h-[24px] w-full resize-none bg-transparent py-1 text-sm leading-relaxed text-ink placeholder:text-ink-placeholder focus:outline-none disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={!canSubmit}
          className="inline-flex h-8 shrink-0 items-center rounded-full bg-primary px-4 text-[11px] font-bold uppercase tracking-[0.03em] text-white transition-colors duration-fast ease-out-quart hover:bg-primary-hover disabled:cursor-not-allowed disabled:bg-line disabled:text-ink-placeholder"
        >
          {busy ? 'Asking…' : 'Ask Naren'}
        </button>
      </div>
      <span className="px-2 text-center text-[11px] text-ink-placeholder">
        Grounded in Naren&rsquo;s real calls &middot; Enter to send, Shift+Enter for a new line
        &middot; Type <span className="font-medium text-ink-2">/help</span> for what to ask
      </span>
    </form>
  );
}
