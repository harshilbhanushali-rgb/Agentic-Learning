'use client';

import { BLOOM_STAGES } from '@/data/workspace';
import { WFCheckIcon, BloomDotIcon, WFLockIcon } from '@/components/icons';

const ROW = {
  done:   'bg-bg border-line-subtle',
  active: 'bg-primary-subtle border-[oklch(0.428_0.198_256_/_0.2)]',
  next:   'bg-bg border-line-subtle',
  locked: 'bg-bg border-line-subtle opacity-60',
};

const IND = {
  done:   'bg-success text-white',
  active: 'bg-primary text-white',
  next:   'bg-surface-raised text-ink-placeholder',
  locked: 'bg-surface-raised text-ink-placeholder',
};

export function BloomCard() {
  return (
    <div className="flex flex-col gap-3 pt-4 border-t border-line-subtle">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-bold text-ink tracking-[-0.01em]">Bloom&apos;s · your path</h3>
        <span className="inline-flex items-center h-[18px] px-2 rounded-full bg-accent-surface text-accent-on text-[10px] font-bold tracking-[0.03em] uppercase shrink-0 mt-0.5">Newbie</span>
      </div>
      <div className="flex flex-col gap-2">
        {BLOOM_STAGES.map((stage, i) => (
          <div key={i} className={`flex items-start gap-3 px-3 py-2 border rounded-sm ${ROW[stage.state] || ROW.next}`}>
            <div className={`w-[18px] h-[18px] rounded-full flex items-center justify-center shrink-0 mt-0.5 ${IND[stage.state] || IND.next}`}>
              {stage.state === 'done'   && <WFCheckIcon />}
              {stage.state === 'active' && <BloomDotIcon />}
              {stage.state === 'locked' && <WFLockIcon />}
            </div>
            <div>
              <div className={`text-xs leading-[1.2] mb-0.5 ${stage.state === 'active' ? 'text-primary font-semibold' : 'text-ink font-medium'}`}>{stage.label}</div>
              <div className="font-mono text-[10px] text-ink-placeholder tracking-[0.04em]">{stage.note}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
