'use client';

import { useRef, useEffect } from 'react';

/**
 * The one input. A textarea rather than a single-line field because a situation is a few
 * sentences of context, and a field that scrolls sideways hides what was typed.
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

  const canSubmit = value.trim().length > 0 && !busy;

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={e => { e.preventDefault(); if (canSubmit) onSubmit(); }}
    >
      <label htmlFor="situation" className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
        The situation
      </label>
      <textarea
        id="situation"
        ref={ref}
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={e => {
          // ⌘/Ctrl+Enter submits. A bare Enter inserts a newline, because a situation is
          // prose and losing a half-typed one to a stray keystroke is worse than a modifier.
          if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && canSubmit) {
            e.preventDefault();
            onSubmit();
          }
        }}
        rows={4}
        placeholder="What did the client say, and what do you need to respond to?"
        disabled={busy}
        className="w-full resize-y rounded-md border border-line bg-surface px-4 py-3 text-sm leading-relaxed text-ink placeholder:text-ink-placeholder transition-colors duration-fast ease-out-quart focus:border-primary focus:outline-none disabled:opacity-60"
      />
      <div className="flex items-center justify-between gap-4">
        <span className="text-[11px] text-ink-placeholder">
          Grounded in Naren&rsquo;s real calls. If nothing close exists, Ask Naren says so
          rather than guessing.
        </span>
        <button
          type="submit"
          disabled={!canSubmit}
          className="inline-flex h-9 shrink-0 items-center rounded-sm border border-primary bg-transparent px-4 text-[11px] font-bold uppercase tracking-[0.03em] text-primary transition-colors duration-fast ease-out-quart hover:bg-primary hover:text-white disabled:cursor-not-allowed disabled:border-line disabled:text-ink-placeholder disabled:hover:bg-transparent"
        >
          {busy ? 'Asking…' : 'Ask Naren'}
        </button>
      </div>
    </form>
  );
}
