'use client';
import type { RadarMeeting } from '@/types';

import { useState } from 'react';
import { RadarBriefingPanel } from '@/components/shared/RadarBriefingPanel';
import { ChevronRightIcon, ChevronDownIcon } from '@/components/icons';

const PREP = {
  'ready':       'bg-success-surface text-success',
  'in-progress': 'bg-warning-surface text-warning',
  'cold':        'bg-error-surface text-error',
};

export function RadarRow({ meeting }: { meeting: RadarMeeting }) {
  const [open, setOpen] = useState(false);
  const chip = PREP[meeting.prepStatus] || PREP['in-progress'];

  return (
    <div className="flex flex-col border-b border-line-subtle last:border-b-0">
      <div
        className="grid grid-cols-[80px_1fr_auto] gap-4 items-center px-5 py-4 cursor-pointer transition-colors duration-fast ease-out-quart hover:bg-surface"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex flex-col gap-0.5">
          <div className="font-mono text-[10px] font-semibold text-ink-2 tracking-[0.06em] uppercase">{meeting.day}</div>
          <div className="text-sm font-semibold text-ink tabular-nums">{meeting.time}</div>
          <div className="text-[10px] font-medium text-primary tracking-[0.02em] uppercase">{meeting.relative}</div>
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-ink mb-0.5 whitespace-nowrap overflow-hidden text-ellipsis">
            <span className="text-ink">{meeting.account}</span>
            <span className="text-ink-2 font-normal"> · {meeting.title}</span>
          </div>
          <div className="text-xs text-ink-placeholder whitespace-nowrap overflow-hidden text-ellipsis">{meeting.tags}</div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`inline-flex items-center h-[22px] px-2 rounded-sm text-[10px] font-bold tracking-[0.03em] uppercase whitespace-nowrap ${chip}`}>{meeting.prepLabel}</span>
          <button
            className="inline-flex items-center gap-1 h-[26px] px-2 rounded-sm border border-line bg-transparent text-xs font-medium text-ink-2 cursor-pointer whitespace-nowrap transition duration-fast ease-out-quart hover:bg-primary-subtle hover:border-primary hover:text-primary"
            onClick={e => { e.stopPropagation(); setOpen(o => !o); }}
          >
            {open ? <>Hide briefing <ChevronDownIcon /></> : <>Open briefing <ChevronRightIcon /></>}
          </button>
        </div>
      </div>

      <div className={`grid transition-[grid-template-rows] duration-slow ease-out-expo ${open ? 'grid-rows-1fr' : 'grid-rows-0fr'}`}>
        <div className="overflow-hidden">
          <RadarBriefingPanel meeting={meeting} />
        </div>
      </div>
    </div>
  );
}
