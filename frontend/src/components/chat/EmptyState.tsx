'use client';

/* Suggestions double as documentation: they are the questions the mock can
 * actually answer, so a first-time visitor sees the product at its best
 * rather than hitting the fallback. */

const SUGGESTIONS = [
  { q: 'QBR opening framework — skeptical CXO', cat: 'Playbooks' },
  { q: 'How should I reframe CPH to brand ROI?', cat: 'Narratives' },
  { q: 'Objection: "We have internal tools"',    cat: 'Objections' },
];

export function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="max-w-content mx-auto pt-12">
        <h1 className="text-2xl font-bold text-ink mb-2">Ask the Oracle</h1>
        <p className="text-sm text-ink-2 leading-base mb-8 max-w-md">
          Every answer is grounded in the team&rsquo;s own calls, modules and post-mortems —
          and shows you exactly where it came from.
        </p>

        <div className="text-[10px] uppercase tracking-[0.06em] text-ink-placeholder font-medium mb-3">
          Try asking
        </div>
        <div className="flex flex-col gap-2 max-w-lg">
          {SUGGESTIONS.map(s => (
            <button
              key={s.q}
              type="button"
              onClick={() => onPick(s.q)}
              className="group flex items-center gap-3 text-left rounded-md border border-line-subtle
                         bg-surface px-4 py-3 hover:border-primary hover:bg-primary-surface
                         transition-colors duration-fast"
            >
              <span className="text-sm text-ink flex-1">{s.q}</span>
              <span className="text-[9px] font-semibold tracking-[0.06em] text-ink-placeholder
                               group-hover:text-primary shrink-0">
                {s.cat.toUpperCase()}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
