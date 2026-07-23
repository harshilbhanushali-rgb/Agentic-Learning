'use client';

import { TEST_QUEUE } from '@/data/workspace';
import { TQItem } from '@/components/shared/TQItem';

export function TestQueuePanel() {
  const activeTier = TEST_QUEUE.find(i => i.status === 'active')?.tier ?? 1;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-ink tracking-[-0.01em]">Test queue</h3>
          <div className="text-[10px] font-medium text-ink-placeholder tracking-[0.04em] uppercase mt-0.5">Waterfall · Tier {activeTier} of 3</div>
        </div>
        <button className="text-xs font-medium text-primary bg-transparent cursor-pointer p-0 whitespace-nowrap shrink-0 mt-0.5 hover:opacity-70">View all</button>
      </div>
      <div className="flex flex-col gap-1">
        {TEST_QUEUE.map(item => <TQItem key={item.id} item={item} tierLabel={`Tier ${item.tier}`} />)}
      </div>
    </div>
  );
}
