import type { CaseStudy } from '@/types';
import { csBars } from '@/data/library';
import { PeopleIcon } from '@/components/icons';

export function CaseStudyCard({ cs, onOpen }: { cs: CaseStudy; onOpen: (cs: CaseStudy) => void }) {
  const written = cs.chapters.length;
  const bars = csBars(cs.account + cs.headline);
  const lastIdx = bars.length - 1;

  return (
    <button className="group flex flex-col border-[1.5px] border-line rounded-md bg-bg overflow-hidden cursor-pointer text-left p-0 transition duration-fast ease-out-quart hover:bg-surface hover:shadow-low hover:-translate-y-[3px]" onClick={() => onOpen(cs)}>
      <div className="relative h-24 px-4 py-3 bg-surface border-b border-line-subtle overflow-hidden transition-colors duration-fast ease-out-quart group-hover:bg-surface-raised" aria-hidden="true">
        <span className="absolute top-3 left-3 font-mono text-[10px] font-semibold tracking-[0.04em] uppercase text-ink-2 bg-bg border border-line rounded-full px-2 py-[3px]">{cs.account}</span>
        {cs.justDropped && (
          <span className="absolute top-3 right-3 inline-flex items-center gap-1 font-mono text-[10px] font-semibold tracking-[0.04em] text-white bg-primary rounded-full px-2 py-[3px]">
            <span className="w-[5px] h-[5px] rounded-full bg-current" />
            Chapter just dropped
          </span>
        )}
        <div className="flex items-end gap-0.5 h-full w-full">
          {bars.map((h, i) => {
            const isLatest = cs.status === 'live' && i === lastIdx;
            const isRecent = !isLatest && i >= lastIdx - 3;
            const barColor = isLatest ? 'bg-primary' : isRecent ? 'bg-[oklch(0.62_0.01_256)]' : 'bg-[oklch(0.86_0.006_256)]';
            return (
              <span
                key={i}
                className={`flex-1 min-w-0 rounded-t-[1.5px] ${barColor}`}
                style={{ height: `${h}%` }}
              />
            );
          })}
        </div>
        <span className="absolute bottom-2 right-3 font-mono text-[10px] font-semibold tracking-[0.06em] uppercase text-ink-placeholder">{cs.sector}</span>
      </div>

      <div className="flex flex-col gap-3 px-5 pt-4 pb-5 flex-1">
        <h3 className="text-base font-semibold text-ink leading-snug tracking-[-0.01em] text-balance">{cs.headline}</h3>
        <div className="font-mono text-[10px] text-ink-2 tracking-[0.04em]">
          {cs.sector} · {cs.region} · {cs.monthsActive} months active
        </div>
        <div className="flex gap-1 mt-auto" aria-hidden="true">
          {Array.from({ length: cs.total }).map((_, i) => {
            const filled = i < written;
            const current = cs.justDropped && i === written - 1;
            const segColor = current ? 'bg-primary' : filled ? 'bg-[oklch(0.55_0.01_256)]' : 'bg-line';
            return <span key={i} className={`flex-1 h-1 rounded-full ${segColor}`} />;
          })}
        </div>
        <div className="flex items-center justify-between gap-3 font-mono text-[10px] font-medium tracking-[0.06em] uppercase text-ink-placeholder">
          <span>Chapters · {written} of {cs.total} · {cs.status === 'live' ? 'Live' : 'Historical'}</span>
          <span className="inline-flex items-center gap-1">
            <PeopleIcon />
            {cs.participants}
          </span>
        </div>
      </div>
    </button>
  );
}
