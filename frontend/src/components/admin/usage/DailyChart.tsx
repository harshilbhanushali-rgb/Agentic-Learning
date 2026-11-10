'use client';

import { useState } from 'react';

import { formatDay } from './format';

type Measure = 'questions' | 'people';

/** Round gridline values from the axis top down to 0: steps of 1, 2 or 5 x 10^n, 2-4 lines. */
export function axis(max: number): number[] {
  const raw = Math.max(max, 1) / 3;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = Math.max(1, [1, 2, 5, 10].map(m => m * pow).find(s => s >= raw)!);
  const top = Math.max(step, Math.ceil(max / step) * step);
  const ticks: number[] = [];
  for (let v = top; v >= 0; v -= step) ticks.push(v);
  return ticks;
}

/** Questions (or people) per India-time day. The last bar is today, still filling up. */
export function DailyChart({ daily }: { daily: { day: string; questions: number; people: number }[] }) {
  const [measure, setMeasure] = useState<Measure>('questions');
  const values = daily.map(d => d[measure]);
  const ticks = axis(Math.max(0, ...values));
  const top = ticks[0];
  const labelEvery = Math.max(1, Math.ceil(daily.length / 6));
  const noun = measure === 'questions' ? 'questions' : 'people';

  return (
    <div className="flex flex-col gap-4">
      <div role="group" aria-label="Measure" className="flex self-start rounded-md bg-surface-raised p-[3px]">
        {(['questions', 'people'] as const).map(m => (
          <button
            key={m}
            type="button"
            aria-pressed={measure === m}
            onClick={() => setMeasure(m)}
            className={`min-h-[32px] rounded-[6px] px-3 text-[12px] font-semibold capitalize transition-colors duration-fast ease-out-quart ${
              measure === m ? 'bg-bg text-ink shadow-low' : 'text-ink-2 hover:text-ink'
            }`}
          >
            {m}
          </button>
        ))}
      </div>

      <div className="flex gap-2.5" aria-hidden="true">
        <div className="-mt-1.5 flex h-[200px] min-w-[24px] flex-col justify-between text-right font-mono text-[11px] text-ink-2">
          {ticks.map(t => <span key={t}>{t}</span>)}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="relative h-[200px] border-b border-line">
            {ticks.slice(0, -1).map(t => (
              <div key={t} className="absolute inset-x-0 border-t border-dashed border-line-subtle" style={{ top: `${(1 - t / top) * 100}%` }} />
            ))}
            <div className="absolute inset-0 flex items-end gap-[2px]">
              {daily.map((d, i) => {
                const today = i === daily.length - 1;
                return (
                  <div
                    key={d.day}
                    title={`${formatDay(d.day)} · ${d.questions} questions from ${d.people} ${d.people === 1 ? 'person' : 'people'}${today ? ' (so far)' : ''}`}
                    className="flex h-full flex-1 items-end hover:bg-surface"
                  >
                    <div
                      className="w-full rounded-t-[4px] bg-primary"
                      style={{ height: `${(d[measure] / top) * 100}%`, opacity: today ? 0.45 : 1 }}
                    />
                  </div>
                );
              })}
            </div>
          </div>
          <div className="flex gap-[2px] font-mono text-[11px] text-ink-2">
            {daily.map((d, i) => (
              <div key={d.day} className="flex-1 overflow-visible whitespace-nowrap">
                {i % labelEvery === 0 ? formatDay(d.day, { weekday: false }) : ''}
              </div>
            ))}
          </div>
        </div>
      </div>

      <table className="sr-only">
        <caption>{`${noun} per day`}</caption>
        <thead><tr><th scope="col">Day</th><th scope="col">Questions</th><th scope="col">People</th></tr></thead>
        <tbody>
          {daily.map(d => (
            <tr key={d.day}><td>{formatDay(d.day)}</td><td>{d.questions}</td><td>{d.people}</td></tr>
          ))}
        </tbody>
      </table>
      <p className="text-[12px] text-ink-2">Today is still filling up, so it’s shown lighter. Hover a bar for that day’s numbers.</p>
    </div>
  );
}
