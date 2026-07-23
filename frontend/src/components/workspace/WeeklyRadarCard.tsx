'use client';

import { RADAR_MEETINGS } from '@/data/workspace';
import { RadarDeckStack } from '@/components/shared/RadarDeckStack';

export function WeeklyRadarCard() {
  const prepped    = RADAR_MEETINGS.filter(m => m.prepStatus === 'ready').length;
  const inProgress = RADAR_MEETINGS.filter(m => m.prepStatus === 'in-progress').length;
  const cold       = RADAR_MEETINGS.filter(m => m.prepStatus === 'cold').length;

  return (
    <div className="border-[1.5px] border-line rounded-md overflow-hidden bg-bg">
      <div className="px-5 pt-4 pb-3 border-b border-line-subtle flex flex-col gap-2">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-bold text-ink tracking-[-0.01em]">Weekly Radar</h2>
          <div className="flex items-center gap-2">
            {prepped > 0    && <span className="inline-flex items-center h-5 px-2 rounded-full text-[10px] font-bold tracking-[0.04em] uppercase whitespace-nowrap bg-success-surface text-success">{prepped} Prepped</span>}
            {inProgress > 0 && <span className="inline-flex items-center h-5 px-2 rounded-full text-[10px] font-bold tracking-[0.04em] uppercase whitespace-nowrap bg-warning-surface text-warning">{inProgress} In Progress</span>}
            {cold > 0       && <span className="inline-flex items-center h-5 px-2 rounded-full text-[10px] font-bold tracking-[0.04em] uppercase whitespace-nowrap bg-error-surface text-error">{cold} Cold</span>}
          </div>
        </div>
        <div className="text-xs text-ink-placeholder tracking-[0.04em] uppercase">Calendar sync · {RADAR_MEETINGS.length} meetings · Click a card to open briefing</div>
      </div>
      <RadarDeckStack meetings={RADAR_MEETINGS} />
    </div>
  );
}
