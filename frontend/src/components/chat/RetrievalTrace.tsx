'use client';

import type { RetrievalSource } from '@/types';

/* Design Principle 5 — show the work. Surfacing what the Oracle consulted
 * (and how many matches it found) is what separates a credible answer from
 * a confident-sounding one. Rendered before the first token arrives, so the
 * wait itself communicates effort. */

export function RetrievalTrace({ sources, live }: { sources: RetrievalSource[]; live: boolean }) {
  if (sources.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 mb-3">
      <span className="text-[10px] uppercase tracking-[0.06em] text-ink-placeholder font-medium">
        {live ? 'Searching' : 'Searched'}
      </span>
      {sources.map(s => (
        <span
          key={s.id}
          className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-sm
                     bg-surface-raised border border-line-subtle text-ink-2"
        >
          {s.label}
          <span className="tabular-nums text-ink-placeholder">{s.matches}</span>
        </span>
      ))}
    </div>
  );
}
