'use client';

import { useState } from 'react';
import { NEWBIE_TRACK } from '@/data/workspace';
import { ChevronRightIcon, ChevronDownIcon, ClockIcon } from '@/components/icons';

export function NewbieTrackHero() {
  const [open, setOpen] = useState(false);
  const t = NEWBIE_TRACK;

  return (
    <div className="border-[1.5px] border-line rounded-md overflow-hidden bg-bg">
      <div className="flex items-center justify-between gap-4 px-4 py-3 bg-surface border-b border-line-subtle">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: 'oklch(0.428 0.198 256)', boxShadow: '0 0 0 3px oklch(0.428 0.198 256 / 0.18)' }} aria-hidden="true" />
          <span className="font-mono text-[10px] font-semibold text-ink-2 tracking-[0.06em] uppercase">3-Month Mandatory Track · Phase {t.phase} of {t.totalPhases}</span>
        </div>
        <span className="font-mono text-[10px] text-ink-placeholder tracking-[0.06em] uppercase whitespace-nowrap">Day {t.day} / {t.totalDays} · Bloom: {t.phaseLabel}</span>
      </div>

      <div className="px-5 pt-5 pb-4 flex flex-col gap-4">
        <div className="flex items-start justify-between gap-5">
          <div>
            <h2 className="text-xl font-bold text-ink leading-snug tracking-[-0.02em] text-balance">Phase {t.phase} · {t.phaseLabel} — {t.progress}% complete</h2>
            <p className="text-sm text-ink-2 leading-base mt-2">
              One module and one case study queued for today. Apply simulations unlock when this phase finishes.
            </p>
          </div>
          <button className="inline-flex items-center gap-1 h-7 px-3 rounded-sm border border-line bg-bg text-xs font-semibold text-ink cursor-pointer whitespace-nowrap transition duration-fast ease-out-quart hover:bg-surface hover:border-ink-2 shrink-0" onClick={() => setOpen(o => !o)}>
            {open ? <>Hide <ChevronDownIcon /></> : <>What&apos;s next <ChevronRightIcon /></>}
          </button>
        </div>

        <div className="mt-4">
          <div className="h-[5px] bg-line rounded-full overflow-hidden mb-3">
            <div className="h-full w-full bg-primary rounded-full origin-left transition-transform duration-slow ease-out-expo" style={{ transform: `scaleX(${t.progress / 100})` }} />
          </div>
          <div className="flex gap-2">
            <div className="flex-1 text-[10px] tracking-[0.02em] text-center text-success">Phase 1 <b className="block font-semibold mt-px text-success">Remember</b></div>
            <div className="flex-1 text-[10px] tracking-[0.02em] text-center text-primary">Phase 2 <b className="block font-semibold mt-px text-primary">Understand</b></div>
            <div className="flex-1 text-[10px] tracking-[0.02em] text-center text-ink-placeholder">Phase 3 <b className="block font-semibold mt-px text-ink-placeholder">Apply</b></div>
          </div>
        </div>
      </div>

      <div className={`grid transition-[grid-template-rows] duration-slow ease-out-expo ${open ? 'grid-rows-1fr' : 'grid-rows-0fr'}`}>
        <div className="overflow-hidden">
          <div className="px-5 py-4 border-t border-line-subtle">
            <div className="text-[10px] font-semibold text-ink-placeholder mb-3">Next up · today</div>
            <div className="flex flex-col gap-2">
              {t.nextUp.map((item, i) => (
                <div key={i} className="flex items-start gap-3 px-4 py-3 border border-line-subtle rounded-md bg-bg">
                  <span className="inline-flex items-center h-[22px] px-2 bg-primary-subtle text-primary rounded-sm text-[10px] font-bold tracking-[0.04em] uppercase whitespace-nowrap shrink-0 mt-px">{item.kind}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-ink leading-snug mb-[3px]">{item.desc}</div>
                    <div className="text-[10px] text-ink-placeholder uppercase tracking-[0.04em]">{item.meta}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="px-5 py-4 bg-surface border-t border-line-subtle flex items-center justify-between gap-4 flex-wrap">
            <span className="text-xs text-ink-2">
              The track <strong>cannot be skipped</strong>. Personalisation unlocks at day {t.totalDays}.
            </span>
            <button className="inline-flex items-center gap-1 h-7 px-3 rounded-sm bg-primary text-white text-xs font-bold tracking-[0.02em] cursor-pointer transition duration-fast ease-out-quart hover:bg-primary-hover">Resume Phase {t.phase} <ChevronRightIcon /></button>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 px-5 py-3 bg-surface border-t border-line-subtle text-xs text-ink-placeholder tracking-[0.03em] uppercase">
        <ClockIcon /><span>Day {t.day} / {t.totalDays}</span>
        <span className="w-px h-2.5 bg-line mx-1 shrink-0" />
        <span>Phase {t.phase} of {t.totalPhases}</span>
        <span className="w-px h-2.5 bg-line mx-1 shrink-0" />
        <span>{t.phaseLabel}</span>
      </div>
    </div>
  );
}
