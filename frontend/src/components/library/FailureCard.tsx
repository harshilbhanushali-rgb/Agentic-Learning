import type { FailureEntry } from '@/types';
import { ArrowIcon } from '@/components/icons';

export function FailureCard({ deal, category, lesson, quarter, entry, onOpen }: { deal: string; category: string; lesson: string; quarter: string; entry: FailureEntry; onOpen: (e: FailureEntry) => void }) {
  return (
    <button className="lib-fl-card relative bg-bg border-[1.5px] border-line rounded-md p-5 cursor-pointer text-left flex flex-col gap-3 min-h-[200px] overflow-hidden transition duration-fast ease-out-quart hover:bg-surface hover:shadow-low hover:-translate-y-[3px]" onClick={() => onOpen(entry)}>
      <div className="flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-2 font-mono text-[10px] font-semibold tracking-[0.06em] uppercase text-ink-2">
          <span className="w-[7px] h-[7px] rounded-full bg-warning shrink-0" />
          {category}
        </span>
        <span className="font-mono text-[10px] text-ink-placeholder font-semibold tracking-[0.06em] uppercase">{quarter}</span>
      </div>
      <div className="text-lg font-bold text-ink tracking-[-0.015em] leading-snug">{deal}</div>
      <p className="text-sm text-ink-2 leading-base line-clamp-3 flex-1">{lesson}</p>
      <div className="flex items-center justify-between gap-3 mt-auto pt-2 border-t border-line-subtle">
        <span className="font-mono text-[10px] text-ink-placeholder font-semibold tracking-[0.06em] uppercase">Post-mortem</span>
        <span className="inline-flex items-center gap-1 text-sm text-primary font-semibold relative z-[1]">
          Read <ArrowIcon />
        </span>
      </div>
    </button>
  );
}
