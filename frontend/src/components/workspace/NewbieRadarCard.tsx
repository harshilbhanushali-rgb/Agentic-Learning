'use client';

import { NEWBIE_RADAR_MEETINGS } from '@/data/workspace';
import { RadarRow } from '@/components/shared/RadarRow';

export function NewbieRadarCard() {
  return (
    <div className="border-[1.5px] border-line rounded-md overflow-hidden bg-bg">
      <div className="px-5 pt-4 pb-3 border-b border-line-subtle flex flex-col gap-2">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-bold text-ink tracking-[-0.01em]">Your week</h2>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center h-5 px-2 rounded-full text-[10px] font-bold tracking-[0.04em] uppercase whitespace-nowrap bg-warning-surface text-warning">Mandatory track prep</span>
          </div>
        </div>
        <div className="text-xs text-ink-placeholder tracking-[0.04em] uppercase">Your first calls are sit-ins — Aryan is the lead</div>
      </div>

      <div className="flex flex-col">
        {NEWBIE_RADAR_MEETINGS.map(m => <RadarRow key={m.id} meeting={m} />)}

        {/* Static internal meeting */}
        <div className="grid grid-cols-[80px_1fr_auto] gap-4 items-center px-5 py-4 cursor-default">
          <div className="flex flex-col gap-0.5">
            <div className="font-mono text-[10px] font-semibold text-ink-2 tracking-[0.06em] uppercase">WED</div>
            <div className="text-sm font-semibold text-ink tabular-nums">3:00 PM</div>
            <div className="text-[10px] font-medium tracking-[0.02em] uppercase text-ink-placeholder">IN 2 DAYS</div>
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-ink mb-0.5">
              <span className="text-ink">Cohort sync</span>
              <span className="text-ink-2 font-normal"> · Track checkpoint</span>
            </div>
            <div className="text-xs text-ink-placeholder">Internal · weekly cohort review</div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="inline-flex items-center h-[22px] px-2 rounded-sm text-[10px] font-bold tracking-[0.03em] uppercase whitespace-nowrap bg-surface-raised text-ink-2">Internal</span>
          </div>
        </div>
      </div>
    </div>
  );
}
