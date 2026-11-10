import type { ReactNode } from 'react';
import Link from 'next/link';

import { AdminTabs } from '@/components/admin/AdminTabs';
import { REGULAR_DAYS, QUIET_DAYS, type UsageRange, type UsageReport } from '@/server/analytics';

import { DailyChart } from './DailyChart';
import { formatWhen, pct, seconds, topicLabel } from './format';

/**
 * The admin Usage page (design: "N10 Usage Analytics" canvas). Presentational only: every
 * number arrives in `report`, computed by src/server/analytics.ts.
 */

const RANGE_LABELS: Record<UsageRange, string> = { '7': '7 days', '30': '30 days', '90': '90 days', all: 'All time' };
const LABEL = 'font-mono text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-2';
const CARD = 'flex min-w-0 flex-col gap-4 rounded-xl border border-line bg-bg p-6';
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function Card({ id, title, sub, className = '', children }: { id: string; title: string; sub?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className={`${CARD} ${className}`}>
      <div className="flex flex-col gap-1">
        <h2 id={id} className="text-[17px] font-bold text-ink">{title}</h2>
        {sub && <p className="text-[13px] leading-relaxed text-ink-2">{sub}</p>}
      </div>
      {children}
    </section>
  );
}

function Bar({ value, max, color = 'bg-primary', height = 'h-2' }: { value: number; max: number; color?: string; height?: string }) {
  return (
    <div className={`${height} rounded-full bg-surface-raised`}>
      <div className={`h-full rounded-full ${color}`} style={{ width: `${max > 0 ? (value / max) * 100 : 0}%` }} />
    </div>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-[14px] text-ink-2">{children}</p>;
}

/* ── Headline numbers ── */

function change(now: number, before: number, asPercent: boolean): { text: string; up: boolean } | null {
  if (now === before) return { text: 'Same as the period before', up: true };
  if (asPercent && before > 0) {
    const d = Math.round(((now - before) / before) * 100);
    return { text: `${d > 0 ? '+' : ''}${d}% vs the period before`, up: d > 0 };
  }
  const d = now - before;
  return { text: `${d > 0 ? '+' : ''}${d} vs the period before`, up: d > 0 };
}

function Tile({ label, value, unit, delta, note }: { label: string; value: string; unit?: string; delta?: { text: string; up: boolean } | null; note: string }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-line bg-bg px-[18px] pb-4 pt-[18px]">
      <div className={LABEL}>{label}</div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-[32px] font-extrabold leading-none tracking-[-0.03em] text-ink">{value}</span>
        {unit && <span className="text-[14px] font-medium text-ink-2">{unit}</span>}
      </div>
      {delta && (
        <span className={`self-start rounded-full px-2 py-[3px] text-[12px] font-semibold ${delta.up ? 'bg-success-surface text-success' : 'bg-warning-surface text-warning'}`}>
          {delta.text}
        </span>
      )}
      <div className="text-[13px] leading-snug text-ink-2">{note}</div>
    </div>
  );
}

function Headline({ r }: { r: UsageReport }) {
  const rated = r.ratings.good + r.ratings.bad;
  const liked = pct(r.ratings.good, rated);
  const answered = pct(r.outcomes.answered, r.questions);
  const daily = pct(r.avgWeekdayPeople, r.activePeople);
  return (
    <section aria-label="Headline numbers" className="grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-3">
      <Tile
        label="Active people"
        value={String(r.activePeople)}
        unit={`of ${r.access.enabled}`}
        delta={r.previous && change(r.activePeople, r.previous.activePeople, false)}
        note="Asked at least one question in this period."
      />
      <Tile
        label="Questions asked"
        value={String(r.questions)}
        delta={r.previous && change(r.questions, r.previous.questions, true)}
        note={r.chats ? `${r.chats} chats · ${(r.questions / r.chats).toFixed(1)} questions per chat.` : 'No chats in this period.'}
      />
      <Tile
        label="Daily active"
        value={r.avgWeekdayPeople.toFixed(1)}
        unit="people"
        note={daily === null ? 'People on an average weekday.' : `On an average weekday — ${daily}% of this period’s users.`}
      />
      <Tile
        label="Liked"
        value={liked === null ? '—' : `${liked}%`}
        note={rated ? `${r.ratings.good} thumbs up · ${r.ratings.bad} down. ${pct(rated, r.questions)}% of answers rated.` : 'No answers rated in this period.'}
      />
      <Tile
        label="Answered"
        value={answered === null ? '—' : `${answered}%`}
        note={r.questions ? `${pct(r.outcomes.clarify, r.questions)}% asked to clarify · ${pct(r.outcomes.declined, r.questions)}% declined.` : 'No questions in this period.'}
      />
      <Tile label="Regulars" value={String(r.access.regulars)} unit="people" note={`Asked on ${REGULAR_DAYS} or more different days.`} />
    </section>
  );
}

/* ── Sections ── */

function Funnel({ r }: { r: UsageReport }) {
  const steps = [
    { label: 'Have access', n: r.access.enabled },
    { label: 'Signed in at least once', n: r.access.signedIn },
    { label: 'Asked a question this period', n: r.access.asked },
    { label: `Asked on ${REGULAR_DAYS}+ days`, n: r.access.regulars },
  ];
  const { neverSignedIn, neverAsked } = r.nudges;
  return (
    <Card id="h-funnel" title="From added to regular" sub="Of everyone who has access, how many actually use it." className="flex-[1_1_340px]">
      <ol className="flex flex-col gap-3.5">
        {steps.map(s => (
          <li key={s.label} className="flex flex-col gap-1.5">
            <div className="flex justify-between gap-2 text-[14px]">
              <span className="font-medium text-ink">{s.label}</span>
              <span className="text-ink"><b>{s.n}</b> <span className="text-ink-2">{pct(s.n, r.access.enabled) ?? 0}%</span></span>
            </div>
            <Bar value={s.n} max={r.access.enabled} height="h-2.5" />
          </li>
        ))}
      </ol>
      {(neverSignedIn.length > 0 || neverAsked.length > 0) && (
        <p className="mt-auto rounded-md bg-primary-surface px-3.5 py-3 text-[13px] leading-relaxed text-ink">
          <b>{neverSignedIn.length}</b> {neverSignedIn.length === 1 ? 'person was' : 'people were'} added but never signed in, and{' '}
          <b>{neverAsked.length}</b> signed in but never asked. See “People to check in with” below.
        </p>
      )}
    </Card>
  );
}

function TopUsers({ r, now }: { r: UsageReport; now: Date }) {
  const max = r.people[0]?.questions ?? 0;
  return (
    <section aria-labelledby="h-top" className="flex min-w-0 flex-[2_1_600px] flex-col gap-3.5 rounded-xl border border-line bg-bg pb-2 pt-6">
      <div className="flex flex-col gap-1 px-6">
        <h2 id="h-top" className="text-[17px] font-bold text-ink">Who uses it most</h2>
        <p className="text-[13px] text-ink-2">Everyone who asked a question in this period, most questions first.</p>
      </div>
      {r.people.length === 0 ? (
        <div className="px-6 pb-4"><Empty>Nobody asked a question in this period.</Empty></div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] border-collapse text-left text-[14px]">
            <thead>
              <tr className={LABEL}>
                <th scope="col" className="py-2 pl-6 pr-3 font-semibold">Person</th>
                <th scope="col" className="px-3 py-2 font-semibold">Questions</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Days active</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Questions / chat</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Liked</th>
                <th scope="col" className="py-2 pl-3 pr-6 text-right font-semibold">Last asked</th>
              </tr>
            </thead>
            <tbody>
              {r.people.map(p => {
                const rated = p.good + p.bad;
                return (
                  <tr key={p.id} className="border-t border-line-subtle">
                    <td className="py-2.5 pl-6 pr-3">
                      <div className="flex flex-col">
                        <span className="font-semibold text-ink">{p.name}</span>
                        <span className="text-[12px] text-ink-2">{p.email}</span>
                      </div>
                    </td>
                    <td className="min-w-[160px] px-3 py-2.5">
                      <div className="flex items-center gap-2.5">
                        <span className="w-8 text-right font-bold tabular-nums text-ink">{p.questions}</span>
                        <div className="flex-1"><Bar value={p.questions} max={max} /></div>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-ink">{p.activeDays}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-ink">{(p.questions / Math.max(1, p.chats)).toFixed(1)}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-ink">
                      {rated ? <>{pct(p.good, rated)}% <span className="text-[12px] text-ink-2">({rated})</span></> : <span className="text-ink-2">—</span>}
                    </td>
                    <td className="whitespace-nowrap py-2.5 pl-3 pr-6 text-right text-ink-2">{p.lastAsked ? formatWhen(p.lastAsked, now) : '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Liking({ r }: { r: UsageReport }) {
  const { good, bad } = r.ratings;
  const rated = good + bad;
  const weeks = r.weeklyRatings.slice(-8);
  return (
    <Card id="h-like" title="Are they liking it?" sub="Thumbs up / down on answers." className="flex-[1_1_340px]">
      {rated === 0 ? (
        <Empty>No answers were rated in this period.</Empty>
      ) : (
        <>
          <div className="flex items-baseline gap-2.5">
            <span className="text-[48px] font-extrabold leading-none tracking-[-0.03em] text-ink">{pct(good, rated)}%</span>
            <span className="text-[14px] text-ink-2">of rated answers got a thumbs up</span>
          </div>
          <div className="flex flex-col gap-2">
            <div role="img" aria-label={`${good} thumbs up, ${bad} thumbs down`} className="flex h-3.5 gap-[2px] overflow-hidden rounded-[4px]">
              {good > 0 && <div className="bg-success" style={{ width: `${(good / rated) * 100}%` }} />}
              {bad > 0 && <div className="bg-error" style={{ width: `${(bad / rated) * 100}%` }} />}
            </div>
            <div className="flex justify-between text-[13px] text-ink">
              <span><b>{good}</b> good</span>
              <span><b>{bad}</b> bad</span>
            </div>
          </div>
          {weeks.length > 1 && (
            <div className="flex flex-col gap-2.5">
              <div className={LABEL}>Thumbs-up share, by week</div>
              <div className="flex h-24 items-end gap-2">
                {weeks.map(w => {
                  const share = pct(w.good, w.good + w.bad) ?? 0;
                  return (
                    <div key={w.week} title={`Week of ${w.week}: ${share}% thumbs up (${w.good + w.bad} rated)`} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
                      <span className="text-[12px] font-semibold text-ink">{share}%</span>
                      <div className="w-full rounded-t-[4px] bg-success" style={{ height: `${share * 0.75}%` }} />
                    </div>
                  );
                })}
              </div>
              <div className="flex gap-2 text-center font-mono text-[11px] text-ink-2">
                {weeks.map(w => <span key={w.week} className="flex-1">{new Date(`${w.week}T12:00:00+05:30`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</span>)}
              </div>
            </div>
          )}
          <p className="mt-auto border-t border-line-subtle pt-3.5 text-[13px] leading-relaxed text-ink-2">
            Only <b className="text-ink">{pct(rated, r.questions)}%</b> of answers get rated, so this leans on the people who bother to click.
          </p>
        </>
      )}
    </Card>
  );
}

function Outcomes({ r }: { r: UsageReport }) {
  const { answered, clarify, declined } = r.outcomes;
  const parts = [
    { label: 'Answered', n: answered, color: 'var(--chart-answered)' },
    { label: 'Asked to clarify', n: clarify, color: 'var(--chart-clarify)' },
    { label: 'Declined', n: declined, color: 'var(--chart-declined)' },
  ].filter(p => p.n > 0);
  const reasons = [
    { label: 'Nothing close in Naren’s calls', hint: 'a coverage gap', n: r.declines.gap },
    { label: 'Too busy', hint: 'too many people asking at once', n: r.declines.busy },
    { label: 'Something broke', hint: 'a service or network error', n: r.declines.broke },
  ];
  const maxReason = Math.max(...reasons.map(x => x.n));
  return (
    <Card id="h-out" title="What happens to a question" sub={`${r.questions} questions in this period.`} className="flex-[1_1_480px]">
      {r.questions === 0 ? (
        <Empty>No questions in this period.</Empty>
      ) : (
        <>
          <div role="img" aria-label={`${answered} answered, ${clarify} asked to clarify, ${declined} declined`} className="flex h-7 gap-[2px] overflow-hidden rounded-[4px]">
            {parts.map(p => <div key={p.label} style={{ width: `${(p.n / r.questions) * 100}%`, background: p.color }} />)}
          </div>
          <ul className="flex flex-wrap gap-x-6 gap-y-2 text-[14px] text-ink">
            {[
              { label: 'Answered', n: answered, color: 'var(--chart-answered)' },
              { label: 'Asked to clarify', n: clarify, color: 'var(--chart-clarify)' },
              { label: 'Declined', n: declined, color: 'var(--chart-declined)' },
            ].map(p => (
              <li key={p.label} className="flex items-center gap-2">
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-[3px]" style={{ background: p.color }} />
                {p.label} <b>{p.n}</b> <span className="text-ink-2">{pct(p.n, r.questions)}%</span>
              </li>
            ))}
          </ul>
          {declined > 0 && (
            <div className="flex flex-col gap-2.5 border-t border-line-subtle pt-4">
              <div className={LABEL}>Why it declined</div>
              {reasons.map(x => (
                <div key={x.label} className="grid grid-cols-[minmax(0,1fr)_40px] items-center gap-x-3 gap-y-1">
                  <span className="text-[14px] text-ink">{x.label} <span className="text-[12px] text-ink-2">· {x.hint}</span></span>
                  <b className="text-right tabular-nums text-ink">{x.n}</b>
                  <Bar value={x.n} max={maxReason} color="bg-[var(--chart-declined)]" />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function When({ r }: { r: UsageReport }) {
  let first = 9;
  let last = 20;
  r.heat.forEach(row => row.forEach((n, h) => {
    if (n > 0) { first = Math.min(first, h); last = Math.max(last, h); }
  }));
  const hours = Array.from({ length: last - first + 1 }, (_, i) => first + i);
  const max = Math.max(0, ...r.heat.flat());
  const shade = (n: number) => {
    if (n === 0) return 'var(--color-surface-raised)';
    const level = Math.ceil((n / max) * 4); // 1..4
    return `color-mix(in oklch, var(--color-primary) ${level * 25}%, var(--color-surface-raised))`;
  };
  const cols = { gridTemplateColumns: `36px repeat(${hours.length}, minmax(0, 1fr))` };
  return (
    <Card id="h-when" title="When people ask" sub="Questions by weekday and hour, India time." className="flex-[1_1_480px]">
      <div className="overflow-x-auto">
        <div role="img" aria-label="Questions by weekday and hour" className="flex min-w-[440px] flex-col gap-[3px]">
          {DAYS.map((d, di) => (
            <div key={d} className="grid items-center gap-[3px]" style={cols}>
              <span className="font-mono text-[11px] text-ink-2">{d}</span>
              {hours.map(h => (
                <div
                  key={h}
                  title={`${d} ${String(h).padStart(2, '0')}:00 · ${r.heat[di][h]} questions`}
                  className="h-[26px] rounded-[4px]"
                  style={{ background: shade(r.heat[di][h]) }}
                />
              ))}
            </div>
          ))}
          <div className="grid gap-[3px] text-center font-mono text-[11px] text-ink-2" style={cols}>
            <span />
            {hours.map(h => <span key={h}>{h}</span>)}
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-ink-2">
        <span>Fewer</span>
        {[0, 1, 2, 3, 4].map(l => (
          <span
            key={l}
            aria-hidden="true"
            className="h-3 w-[18px] rounded-[3px]"
            style={{ background: l === 0 ? 'var(--color-surface-raised)' : `color-mix(in oklch, var(--color-primary) ${l * 25}%, var(--color-surface-raised))` }}
          />
        ))}
        <span>More</span>
        {r.wait && (
          <span className="ml-auto">
            Typical wait for an answer: <b className="text-ink">{seconds(r.wait.p50)}</b> · 9 in 10 under {seconds(r.wait.p90)}
          </span>
        )}
      </div>
    </Card>
  );
}

function Topics({ r }: { r: UsageReport }) {
  const shown = r.topics.slice(0, 8);
  const max = Math.max(0, ...shown.map(t => t.questions));
  return (
    <Card
      id="h-topics"
      title="What they ask about"
      sub="By the situation in Naren’s calls that the answer drew on. A low “liked” shows where answers are weakest."
      className="flex-[1_1_400px]"
    >
      {shown.length === 0 ? (
        <Empty>No questions in this period.</Empty>
      ) : (
        <>
          <div className={`grid grid-cols-[minmax(0,1fr)_44px_56px] gap-x-3 ${LABEL}`}>
            <span>Topic</span><span className="text-right">Qs</span><span className="text-right">Liked</span>
          </div>
          {shown.map(t => {
            const rated = t.good + t.bad;
            const liked = pct(t.good, rated);
            const weak = liked !== null && rated >= 3 && liked < 70;
            return (
              <div key={t.key ?? '(none)'} className="grid grid-cols-[minmax(0,1fr)_44px_56px] items-center gap-x-3">
                <div className="flex min-w-0 flex-col gap-1.5">
                  <span className="truncate text-[14px] text-ink">{topicLabel(t.key)}</span>
                  <Bar value={t.questions} max={max} height="h-1.5" />
                </div>
                <b className="text-right text-[14px] tabular-nums text-ink">{t.questions}</b>
                <span
                  title={rated ? `${t.good} up, ${t.bad} down` : 'No ratings'}
                  className={`rounded-md px-1.5 py-0.5 text-right text-[13px] font-semibold ${weak ? 'bg-error-surface text-error' : 'text-ink'}`}
                >
                  {liked === null ? '—' : `${liked}%`}
                </span>
              </div>
            );
          })}
          {r.topics.length > shown.length && (
            <p className="text-[12px] text-ink-2">And {r.topics.length - shown.length} more topics with fewer questions.</p>
          )}
        </>
      )}
    </Card>
  );
}

function ThumbsDown({ r, now }: { r: UsageReport; now: Date }) {
  return (
    <Card
      id="h-bad"
      title="Latest thumbs-down"
      sub={`What was asked, and why the person didn’t like the answer. ${r.ratings.bad} in this period.`}
      className="flex-[2_1_560px]"
    >
      {r.thumbsDown.length === 0 ? (
        <Empty>No thumbs-down in this period.</Empty>
      ) : (
        <ul className="flex flex-col">
          {r.thumbsDown.map((b, i) => (
            <li key={i} className="flex flex-col gap-1.5 border-t border-line-subtle py-3.5">
              <p className="text-[15px] font-semibold leading-snug text-ink">“{b.question}”</p>
              <p className="text-[13px] text-ink-2">{b.name} · {topicLabel(b.topic)} · {formatWhen(b.at, now)}</p>
              {b.reason ? (
                <p className="mt-0.5 rounded-md bg-error-surface px-3 py-2 text-[14px] leading-relaxed text-ink">
                  <b className="text-error">Why:</b> {b.reason}
                </p>
              ) : (
                <p className="mt-0.5 text-[13px] italic text-ink-2">No reason given</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Gaps({ r, now }: { r: UsageReport; now: Date }) {
  return (
    <Card
      id="h-gaps"
      title="Questions Naren’s calls don’t cover"
      sub={`Declined because nothing close enough was found — ${r.declines.gap} in this period. Busy and error declines are left out.`}
      className="flex-[1_1_480px]"
    >
      {r.gaps.length === 0 ? (
        <Empty>None in this period.</Empty>
      ) : (
        <ul className="flex flex-col">
          {r.gaps.map((g, i) => (
            <li key={i} className="flex justify-between gap-4 border-t border-line-subtle py-3">
              <span className="text-[14px] leading-snug text-ink">“{g.question}”</span>
              <span className="whitespace-nowrap text-[12px] text-ink-2">{g.name} · {formatWhen(g.at, now)}</span>
            </li>
          ))}
        </ul>
      )}
      {r.declines.gap > r.gaps.length && <p className="text-[12px] text-ink-2">Showing the latest {r.gaps.length}.</p>}
    </Card>
  );
}

function Nudges({ r, now }: { r: UsageReport; now: Date }) {
  const groups = [
    { label: 'Added, never signed in', people: r.nudges.neverSignedIn.map(p => ({ ...p, meta: '' })) },
    { label: 'Signed in, never asked', people: r.nudges.neverAsked.map(p => ({ ...p, meta: '' })) },
    { label: `Gone quiet — nothing in ${QUIET_DAYS}+ days`, people: r.nudges.goneQuiet.map(p => ({ ...p, meta: formatWhen(p.lastAsked, now) })) },
  ];
  return (
    <Card id="h-nudge" title="People to check in with" sub="They have access but aren’t getting value from it yet. Not affected by the time range." className="flex-[1_1_480px]">
      {groups.map(g => (
        <div key={g.label} className="flex flex-col gap-2.5">
          <div className="flex justify-between gap-2 text-[14px] text-ink">
            <b>{g.label}</b>
            <span className="text-ink-2">{g.people.length === 1 ? '1 person' : `${g.people.length} people`}</span>
          </div>
          {g.people.length === 0 ? (
            <Empty>Nobody.</Empty>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {g.people.map(p => (
                <li key={p.email} title={p.email} className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1.5 text-[13px] text-ink">
                  {p.name}
                  {p.meta && <span className="text-ink-2">· {p.meta}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </Card>
  );
}

/* ── The page ── */

export function UsageDashboard({ range, report }: { range: UsageRange; report: UsageReport | null }) {
  const period = range === 'all' ? 'all time' : `last ${range} days`;
  const now = report?.to ?? new Date();
  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-5 px-4 py-10 sm:px-6">
      <AdminTabs current="usage" />
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h1 className="text-[28px] font-extrabold tracking-[-0.025em] text-ink">Usage</h1>
          <p className="text-[14px] text-ink-2">How the team is using N10 · {period} · India time</p>
        </div>
        <nav aria-label="Time range" className="flex gap-[2px] rounded-md bg-surface-raised p-[3px]">
          {(Object.keys(RANGE_LABELS) as UsageRange[]).map(k => (
            <Link
              key={k}
              href={`/admin/usage?range=${k}`}
              aria-current={k === range ? 'page' : undefined}
              className={`flex min-h-[36px] items-center rounded-[6px] px-3.5 text-[13px] font-semibold transition-colors duration-fast ease-out-quart ${
                k === range ? 'bg-bg text-ink shadow-low' : 'text-ink-2 hover:text-ink'
              }`}
            >
              {RANGE_LABELS[k]}
            </Link>
          ))}
        </nav>
      </header>

      {report === null ? (
        <p role="alert" className="text-[14px] text-error">
          Could not load usage just now. This is a fault on our side — try again in a moment.
        </p>
      ) : (
        <>
          <Headline r={report} />
          <div className="flex flex-wrap gap-5">
            <Card id="h-daily" title="Questions per day" sub="Each bar is one day, India time." className="flex-[2_1_600px]">
              {report.daily.length === 0 ? <Empty>No questions yet.</Empty> : <DailyChart daily={report.daily} />}
            </Card>
            <Funnel r={report} />
          </div>
          <div className="flex flex-wrap gap-5">
            <TopUsers r={report} now={now} />
            <Liking r={report} />
          </div>
          <div className="flex flex-wrap gap-5">
            <Outcomes r={report} />
            <When r={report} />
          </div>
          <div className="flex flex-wrap gap-5">
            <Topics r={report} />
            <ThumbsDown r={report} now={now} />
          </div>
          <div className="flex flex-wrap gap-5">
            <Gaps r={report} now={now} />
            <Nudges r={report} now={now} />
          </div>
          <p className="text-center text-[12px] text-ink-2">
            Removed chats still count. Disabled people’s questions count, but they are left out of “have access”.
          </p>
        </>
      )}
    </div>
  );
}
