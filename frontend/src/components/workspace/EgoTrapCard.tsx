'use client';
import type { Moment } from '@/types';

import { useState } from 'react';
import { EGO_TRAPS } from '@/data/workspace';
import { ChevronRightIcon, ChevronDownIcon, ClockIcon, WaveIcon, PersonIcon } from '@/components/icons';

function Moments({ moments, cardCls }: { moments: Moment[]; cardCls: string }) {
  return (
    <div className="flex flex-col gap-2">
      {moments.map((m, i) => (
        <div key={i} className={`px-4 py-3 border rounded-md ${cardCls}`}>
          <div className="inline-flex items-center px-1.5 py-0.5 bg-bg rounded-sm text-[11px] font-semibold tabular-nums text-ink-2 tracking-[0.02em] mb-2">{m.time}</div>
          <p className="text-sm text-ink leading-base mb-2">{m.quote}</p>
          <div className="text-[10px] text-ink-placeholder uppercase tracking-[0.04em] font-medium">{m.source}</div>
        </div>
      ))}
    </div>
  );
}

export function EgoTrapCard() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [mirrorOpen, setMirrorOpen] = useState(false);
  const trap = EGO_TRAPS[activeIndex];

  const selectTrap = (i: number) => {
    if (i === activeIndex) return;
    setMirrorOpen(false);
    setActiveIndex(i);
  };

  return (
    <div className="border-[1.5px] border-line rounded-md overflow-hidden bg-bg">
      <div className="flex items-center justify-between gap-4 px-4 py-3 bg-surface border-b border-line-subtle">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: 'oklch(0.428 0.198 256)', boxShadow: '0 0 0 3px oklch(0.428 0.198 256 / 0.18)' }} aria-hidden="true" />
          <span className="font-mono text-[10px] font-semibold text-ink-2 tracking-[0.06em] uppercase">Ego Trap · Fires every day</span>
        </div>
        <span className="font-mono text-[10px] text-ink-placeholder tracking-[0.06em] uppercase whitespace-nowrap">Generated {trap.generatedAt} · Transcript processed</span>
      </div>

      <div className="relative border-b border-line-subtle after:content-[''] after:absolute after:right-0 after:top-0 after:w-12 after:h-full after:bg-gradient-to-l after:from-bg after:pointer-events-none">
        <div className="flex gap-2 px-5 py-3 overflow-x-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden" role="tablist" aria-label="This week's meetings">
          {EGO_TRAPS.map((t, i) => {
            const active = i === activeIndex;
            return (
              <button
                key={i}
                role="tab"
                aria-selected={active}
                className={`inline-flex items-center px-2.5 py-1 border rounded-[100px] text-[11px] font-semibold tracking-[0.04em] uppercase whitespace-nowrap cursor-pointer transition duration-fast ease-out-quart ${active ? 'text-ink bg-surface-raised border-line' : 'text-ink-2 border-line bg-transparent hover:text-ink hover:bg-surface'}`}
                onClick={() => selectTrap(i)}
              >
                {t.day} · {t.account}
              </button>
            );
          })}
        </div>
      </div>

      <div className="px-5 pt-5 pb-4 flex flex-col gap-4">
        <div className="flex items-start justify-between gap-5">
          <h2 className="text-xl font-bold text-ink leading-snug tracking-[-0.02em] text-balance">{trap.question}</h2>
          <div className="flex items-center gap-2 shrink-0">
            <span className="inline-flex items-center h-7 px-3 rounded-sm border border-line text-xs font-semibold text-ink-2 tracking-[0.03em] uppercase whitespace-nowrap">Mirror · Not a score</span>
            <button className="inline-flex items-center gap-1 h-7 px-3 rounded-sm border border-line bg-bg text-xs font-semibold text-ink cursor-pointer whitespace-nowrap transition duration-fast ease-out-quart hover:bg-surface hover:border-ink-2" onClick={() => setMirrorOpen(o => !o)}>
              {mirrorOpen ? <>Hide mirror <ChevronDownIcon /></> : <>View mirror <ChevronRightIcon /></>}
            </button>
          </div>
        </div>
        <p className="text-sm text-ink-2 leading-base">
          {trap.applied} moments applied · {trap.missed} moments missed
          {' '}· cross-referenced against {trap.modules} modules and {trap.failureStories} failure stories.
        </p>
      </div>

      <div className={`grid transition-[grid-template-rows] duration-slow ease-out-expo ${mirrorOpen ? 'grid-rows-1fr' : 'grid-rows-0fr'}`}>
        <div className="overflow-hidden">
          <div className="grid grid-cols-1 sm:grid-cols-2 border-t border-line-subtle">
            <div className="px-5 py-4 border-b sm:border-b-0 sm:border-r border-line-subtle">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[10px] font-bold tracking-[0.06em] uppercase text-success">What you applied</span>
                <span className="w-[18px] h-[18px] rounded-full flex items-center justify-center text-[10px] font-bold bg-success-surface text-success">{trap.appliedMoments.length}</span>
              </div>
              <Moments moments={trap.appliedMoments} cardCls="bg-success-surface border-[oklch(0.415_0.140_150_/_0.2)]" />
            </div>
            <div className="px-5 py-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[10px] font-bold tracking-[0.06em] uppercase text-warning">What you missed</span>
                <span className="w-[18px] h-[18px] rounded-full flex items-center justify-center text-[10px] font-bold bg-warning-surface text-warning">{trap.missedMoments.length}</span>
              </div>
              <Moments moments={trap.missedMoments} cardCls="bg-warning-surface border-[oklch(0.415_0.128_68_/_0.2)]" />
            </div>
          </div>

          <div className="px-5 py-4 bg-surface border-t border-line-subtle flex items-center justify-between gap-4 flex-wrap">
            <span className="text-xs text-ink-2">
              Full post-mortem on this pattern is in the <strong>Failure Library</strong>.
            </span>
            <button className="inline-flex items-center gap-1 h-7 px-3 rounded-sm bg-primary text-white text-xs font-bold tracking-[0.02em] cursor-pointer transition duration-fast ease-out-quart hover:bg-primary-hover">Practice in Simulator <ChevronRightIcon /></button>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 px-5 py-3 bg-surface border-t border-line-subtle text-xs text-ink-placeholder tracking-[0.03em] uppercase">
        <ClockIcon /><span>{trap.duration}</span>
        <span className="w-px h-2.5 bg-line mx-1 shrink-0" />
        <WaveIcon /><span>{trap.source}</span>
        <span className="w-px h-2.5 bg-line mx-1 shrink-0" />
        <PersonIcon /><span>{trap.participants} Participants</span>
      </div>
    </div>
  );
}
