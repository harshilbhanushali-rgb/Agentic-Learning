'use client';
import type { RadarMeeting } from '@/types';

import {
  PlayIcon, SparkleIcon, WFCheckIcon, WFLockIcon, WaveformViz, ChevronRightIcon,
} from '@/components/icons';

export function RadarBriefingPanel({ meeting }: { meeting: RadarMeeting }) {
  const ctaLabel = meeting.prepStatus === 'cold'
    ? 'Start Step 01'
    : meeting.prepStatus === 'in-progress'
    ? 'Continue Step 02'
    : null;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 px-5 pt-5 pb-6 border-t border-line-subtle bg-surface">
      {/* LEFT: clip + AI tip */}
      <div>
        <div className="text-[10px] font-semibold text-ink-placeholder mb-3">{meeting.clip.label || 'Expert clip · 2 min'}</div>
        <div className="px-4 py-3 border border-line rounded-md bg-bg flex items-start gap-3 mb-4">
          <button className="w-7 h-7 rounded-full bg-ink text-bg flex items-center justify-center shrink-0 mt-0.5 transition-colors duration-fast ease-out-quart hover:bg-primary" aria-label="Play clip">
            <PlayIcon />
          </button>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-ink leading-snug italic mb-1">&ldquo;{meeting.clip.quote}&rdquo;</div>
            <div className="text-[10px] text-ink-placeholder uppercase tracking-[0.04em]">{meeting.clip.meta}</div>
          </div>
          <div className="text-ink-placeholder shrink-0 self-center" aria-hidden="true"><WaveformViz /></div>
        </div>

        <div className="text-[10px] font-semibold text-ink-placeholder mb-3">AI tip · account health</div>
        <div className="px-4 py-3 border rounded-md bg-primary-subtle flex items-start gap-3" style={{ borderColor: 'oklch(0.428 0.198 256 / 0.2)' }}>
          <div className="w-[22px] h-[22px] rounded-full bg-primary text-white flex items-center justify-center shrink-0 mt-px"><SparkleIcon /></div>
          <p className="text-xs text-ink leading-base">{meeting.tip}</p>
        </div>
      </div>

      {/* RIGHT: waterfall */}
      <div>
        <div className="flex items-center justify-between gap-3 mb-3">
          <div className="text-[10px] font-semibold text-ink-placeholder">Mission Briefing · locked sequence</div>
          <div className="text-[10px] font-semibold text-ink-placeholder">{meeting.industry}</div>
        </div>

        <div className="flex flex-col gap-2">
          {meeting.waterfall.map((step, i) => {
            const stateCls = step.state === 'done' ? 'opacity-[0.65]'
              : step.state === 'active' ? 'border-primary bg-primary-subtle'
              : step.state === 'locked' ? 'opacity-[0.45]' : '';
            const numCls = step.state === 'active' ? 'text-primary' : 'text-ink-placeholder';
            const titleCls = step.state === 'active' ? 'text-primary' : 'text-ink';
            return (
              <div
                key={i}
                className={`border border-line rounded-sm px-4 py-3 bg-bg transition-colors duration-fast ease-out-quart ${stateCls}`}
                title={step.state === 'locked' ? (step.meta && step.meta !== 'Locked' ? step.meta : 'Complete the previous step to unlock') : undefined}
                aria-disabled={step.state === 'locked' ? 'true' : undefined}
              >
                <div className="flex items-center justify-between mb-[3px]">
                  <span className={`text-[10px] font-semibold ${numCls}`}>Step {String(i + 1).padStart(2, '0')} · {step.kind}</span>
                  <span className="flex items-center justify-center">
                    {step.state === 'done'   && <span className="text-success"><WFCheckIcon /></span>}
                    {step.state === 'locked' && <span className="text-ink-placeholder"><WFLockIcon /></span>}
                    {step.state === 'active' && <span className="text-[9px] font-bold bg-primary text-white px-1.5 py-0.5 rounded-full tracking-[0.04em] uppercase">Now</span>}
                  </span>
                </div>
                <div className={`text-sm font-semibold mb-0.5 ${titleCls}`}>{step.label}</div>
                <div className="text-[11px] text-ink-placeholder">{step.meta}</div>
              </div>
            );
          })}
        </div>

        <div className="flex items-center justify-between gap-4 mt-4 flex-wrap">
          <span className="text-[11px] text-ink-2 leading-snug flex-1 min-w-0">
            Once the waterfall is done, this card flips to <strong>You&apos;re prepped</strong>.
          </span>
          {ctaLabel && (
            <button className="inline-flex items-center gap-1 h-7 px-3 rounded-sm bg-ink text-bg text-xs font-bold whitespace-nowrap tracking-[0.02em] shrink-0 transition-colors duration-fast ease-out-quart hover:bg-primary">
              {ctaLabel} <ChevronRightIcon />
            </button>
          )}
          {meeting.prepStatus === 'ready' && (
            <span style={{ fontSize: '11px', color: 'var(--color-success)', fontWeight: 600 }}>✓ Ready to walk in</span>
          )}
        </div>
      </div>
    </div>
  );
}
