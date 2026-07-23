'use client';
import type { TestQueueItem } from '@/types';

import { TQCheckIcon, TQRadioIcon, TQLockIcon } from '@/components/icons';

const IND_COLOR = { complete: 'text-success', active: 'text-primary', locked: 'text-ink-placeholder' };
const TITLE_COLOR = { complete: 'text-ink-2', active: 'text-ink', locked: 'text-ink-placeholder' };

export function TQItem({ item, tierLabel }: { item: TestQueueItem; tierLabel: string }) {
  return (
    <div
      className="flex items-start gap-3 px-3 py-3 rounded-sm transition-colors duration-fast ease-out-quart hover:bg-surface-raised"
      title={item.status === 'locked' ? 'Complete the previous test to unlock' : undefined}
      aria-disabled={item.status === 'locked' ? 'true' : undefined}
    >
      <div className={`w-4 shrink-0 mt-0.5 flex items-center justify-center ${IND_COLOR[item.status]}`} aria-hidden="true">
        {item.status === 'complete' && <TQCheckIcon />}
        {item.status === 'active'   && <TQRadioIcon />}
        {item.status === 'locked'   && <TQLockIcon />}
      </div>
      <div className="flex-1 min-w-0">
        <div className={`text-xs font-medium leading-snug ${TITLE_COLOR[item.status]}`}>{item.title}</div>
        <div className="text-[10px] text-ink-placeholder mt-0.5 tracking-[0.02em] uppercase">
          {tierLabel} · {item.level}
          {item.scored != null && <span> · Scored {item.scored}</span>}
          {item.time   != null && <span> · {item.time}</span>}
        </div>
        {item.note && (
          <div className="text-[10px] text-primary font-medium mt-[3px] tracking-[0.02em] uppercase leading-[1.3]">{item.note}</div>
        )}
      </div>
      {item.status === 'active' && (
        <button className="inline-flex items-center h-6 px-2 rounded-sm border border-primary bg-transparent text-[10px] font-bold text-primary uppercase tracking-[0.03em] shrink-0 mt-0.5 transition-colors duration-fast ease-out-quart hover:bg-primary hover:text-white">Take</button>
      )}
    </div>
  );
}
