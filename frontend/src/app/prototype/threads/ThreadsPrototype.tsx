'use client';

/**
 * PROTOTYPE (issue #39) — THROWAWAY. Three structurally different answers to "where do stored
 * threads live on /ask-naren?", switchable via `?variant=A|B|C`:
 *
 *   A  Left rail on the Ask Naren page (list + open thread side by side)
 *   B  A separate list page, /ask-naren/threads, with each thread at its own URL
 *   C  Today's single-column page plus a compact "Recent threads" dropdown by "New thread"
 *
 * Toggles (all in the floating bar): `cards=full|reduced` — how a resumed thread renders;
 * `state=threads|empty|signed-out`; `resume=continue|read-only` — can an old thread be asked in.
 *
 * Mock data only, no fetch, no storage, no sign-in gate. NO useMode(), same as the real page.
 * Rename / delete / search mutate in-memory state and are flagged "day one?".
 */
import type { AskNarenResponse } from '@/types';

import { useMemo, useState } from 'react';

import { AnswerCard } from '@/components/ask-naren/AnswerCard';
import { DeclineNotice } from '@/components/ask-naren/DeclineNotice';
import { SituationForm } from '@/components/ask-naren/SituationForm';
import { SearchIcon, ChevronDownIcon, ChevronLeftIcon } from '@/components/icons';
import { scenarioLabel, turnFrom } from '@/lib/thread';

import {
  type MockThread, NOW, THREADS, bucket, deriveTitle, firstSituation, lastAskedAt, relative,
} from './mock';

export type Cards = 'full' | 'reduced';
export type PState = 'threads' | 'empty' | 'signed-out';
export type Resume = 'continue' | 'read-only';

interface Common {
  cards: Cards;
  resume: Resume;
  threads: MockThread[];
  rename: (id: string, title: string) => void;
  remove: (id: string) => void;
}

/* ---------- tiny local icons (prototype only; real ones belong in components/icons) ---------- */

function PencilIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" />
    </svg>
  );
}

/* ---------- shared bits ---------- */

/** Marks a feature whose day-one status is the question. Dashed, not amber: it is a note. */
function DayOne({ children = 'day one?' }: { children?: string }) {
  return (
    <span className="inline-flex shrink-0 items-center rounded-sm border border-dashed border-ink-placeholder px-1.5 py-px text-[9px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
      {children}
    </span>
  );
}

function Asked({ message }: { message: string }) {
  return (
    <div className="flex flex-col gap-1.5 border-l-2 border-line pl-4">
      <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
        You asked
      </span>
      <p className="text-[13px] leading-relaxed text-ink-2">{message}</p>
    </div>
  );
}

function Outcome({ result }: { result: AskNarenResponse }) {
  if (result.outcome === 'answered') return <AnswerCard result={result} />;
  if (result.outcome === 'declined') return <DeclineNotice result={result} />;
  return null; // mock data has no clarify/rendered turns
}

/** Copy of AskNaren.tsx's PastTurn — what a reloaded thread looks like TODAY. */
function PastTurn({ message, result }: { message: string; result: AskNarenResponse }) {
  const turn = turnFrom(message, result);
  return (
    <div className="flex flex-col gap-3">
      <Asked message={turn.message} />
      <div className="rounded-md border border-line-subtle bg-surface-raised px-6 py-4">
        <p className="whitespace-pre-line text-[13px] leading-relaxed text-ink-2">{turn.reply}</p>
        {turn.call_filename && (
          <p className="mt-3 break-all border-t border-line-subtle pt-3 text-[11px] text-ink-placeholder">
            {scenarioLabel(turn.scenario_key)} · {turn.call_filename}
          </p>
        )}
      </div>
    </div>
  );
}

function Composer({ placeholderNote }: { placeholderNote?: string }) {
  const [draft, setDraft] = useState('');
  const [sent, setSent] = useState(false);
  return (
    <div className="flex flex-col gap-2">
      <SituationForm value={draft} onChange={setDraft} onSubmit={() => setSent(true)} busy={false} />
      {placeholderNote && <p className="text-[11px] text-ink-placeholder">{placeholderNote}</p>}
      {sent && <p className="text-[11px] text-ink-placeholder">(prototype — nothing was sent)</p>}
    </div>
  );
}

/** One open thread: composer (or read-only notice), then its turns. */
function OpenThread({ thread, cards, resume, onNew }: {
  thread: MockThread; cards: Cards; resume: Resume; onNew: () => void;
}) {
  const days = Math.floor((NOW - lastAskedAt(thread)) / 86400000);
  return (
    <div className="flex flex-col gap-8">
      {resume === 'continue' ? (
        <Composer
          placeholderNote={
            thread.turns.length > 1 || days > 0
              ? `Continuing this thread. A follow-up is answered from the call its last answer came from — last asked ${relative(lastAskedAt(thread)).toLowerCase()}.`
              : undefined
          }
        />
      ) : (
        <div className="flex items-center justify-between gap-4 rounded-md border border-dashed border-line px-5 py-4">
          <p className="text-[13px] leading-relaxed text-ink-2">
            This thread is kept for reading back. A new question starts a new thread.
          </p>
          <button type="button" onClick={onNew}
            className="inline-flex h-8 shrink-0 items-center rounded-sm border border-primary px-3 text-[11px] font-bold uppercase tracking-[0.03em] text-primary hover:bg-primary hover:text-white">
            Ask something new
          </button>
        </div>
      )}
      <section className="flex flex-col gap-8">
        {thread.turns.map((t, i) => (
          <div key={i} className="flex flex-col gap-4">
            <div className="text-[10px] uppercase tracking-[0.06em] text-ink-placeholder">
              {relative(new Date(t.askedAt).getTime())}
            </div>
            {cards === 'full' ? (
              <>
                <Asked message={t.message} />
                <Outcome result={t.response} />
              </>
            ) : (
              <PastTurn message={t.message} result={t.response} />
            )}
          </div>
        ))}
      </section>
    </div>
  );
}

/** A thread's row actions: rename inline, delete with a confirm that says what it does. */
function RowActions({ thread, remove, onEditing }: {
  thread: MockThread; remove: Common['remove']; onEditing: (v: boolean) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const icon = 'rounded-sm p-1 text-ink-placeholder hover:bg-surface-raised hover:text-ink';
  if (confirming) {
    return (
      <div className="mt-2 flex flex-col gap-2 rounded-md border border-line bg-surface p-3 text-[11px] leading-relaxed text-ink-2">
        <span>
          Delete &ldquo;{deriveTitle(thread)}&rdquo;? It disappears from your list.
          <span className="text-ink-placeholder"> [Undecided, #39: are its analytics rows deleted too, and does this copy say so?]</span>
        </span>
        <div className="flex gap-2">
          <button type="button" className="rounded-sm border border-line px-2 py-1" onClick={() => setConfirming(false)}>Cancel</button>
          <button type="button" className="rounded-sm border border-error px-2 py-1 text-error" onClick={() => remove(thread.id)}>Delete</button>
        </div>
      </div>
    );
  }
  return (
    <span className="flex items-center gap-0.5">
      <button type="button" className={icon} aria-label="Rename" title="Rename (day one?)"
        onClick={e => { e.stopPropagation(); onEditing(true); }}>
        <PencilIcon />
      </button>
      <button type="button" className={icon} aria-label="Delete" title="Delete (day one?)"
        onClick={e => { e.stopPropagation(); setConfirming(true); }}>
        <TrashIcon />
      </button>
    </span>
  );
}

function TitleOrEditor({ thread, editing, setEditing, rename, className }: {
  thread: MockThread; editing: boolean; setEditing: (v: boolean) => void;
  rename: Common['rename']; className: string;
}) {
  const [value, setValue] = useState(deriveTitle(thread));
  if (!editing) return <span className={className}>{deriveTitle(thread)}</span>;
  return (
    <input
      autoFocus
      value={value}
      onClick={e => e.stopPropagation()}
      onChange={e => setValue(e.target.value)}
      onBlur={() => { rename(thread.id, value); setEditing(false); }}
      onKeyDown={e => { if (e.key === 'Enter') { rename(thread.id, value); setEditing(false); } }}
      className="w-full rounded-sm border border-primary bg-surface px-2 py-1 text-[12px] text-ink focus:outline-none"
    />
  );
}

function SearchBox({ value, onChange, wide }: { value: string; onChange: (v: string) => void; wide?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <label className={`flex items-center gap-2 rounded-md border border-line bg-surface px-3 ${wide ? 'py-2.5' : 'py-1.5'} text-ink-placeholder focus-within:border-primary`}>
        <SearchIcon />
        <input
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder="Search your threads"
          className="w-full bg-transparent text-[12px] text-ink placeholder:text-ink-placeholder focus:outline-none"
        />
        <DayOne>candidate</DayOne>
      </label>
    </div>
  );
}

const matches = (t: MockThread, q: string) =>
  !q || t.turns.some(turn => turn.message.toLowerCase().includes(q.toLowerCase())) ||
  deriveTitle(t).toLowerCase().includes(q.toLowerCase());

function Header({ right, sub }: { right?: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <header className="flex flex-col gap-2">
      <div className="flex items-start justify-between gap-4">
        <h1 className="text-2xl font-bold tracking-[-0.01em] text-ink">Ask Naren</h1>
        {right}
      </div>
      {sub ?? (
        <p className="text-sm leading-relaxed text-ink-2">
          Describe a live client situation. You get back the answer Naren gave when he faced the
          closest thing to it, with the call it came from.
        </p>
      )}
      <div className="flex items-center gap-2 text-[11px] text-ink-placeholder">
        <span>Signed in as Priya Sharma</span><span aria-hidden="true">·</span><span className="underline">Sign out</span>
      </div>
    </header>
  );
}

const NEW_BTN =
  'inline-flex h-8 shrink-0 items-center rounded-sm border border-line px-3 text-[11px] font-bold uppercase tracking-[0.03em] text-ink-2 hover:border-primary hover:text-primary';

/** Empty-state starters, drawn from the situations the corpus covers best. A candidate. */
function Starters() {
  const items = [
    'A client asked how long the ATS integration takes on their side',
    'A client is moving their XML feed over from another vendor',
    'Legal is redlining the MSA and the client wants to wait',
  ];
  return (
    <div className="flex flex-col gap-3 rounded-md border border-line-subtle bg-surface-raised px-6 py-5">
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
          Where Naren&rsquo;s calls go deepest
        </span>
        <DayOne>candidate</DayOne>
      </div>
      <ul className="flex flex-col gap-1.5 text-[13px] leading-relaxed text-ink-2">
        {items.map(i => <li key={i}>&mdash; {i}</li>)}
      </ul>
      <p className="text-[11px] text-ink-placeholder">
        Getting clients contracted, integrated and live. Questions about rescuing a running campaign
        are declined more often — there is less of that on record.
      </p>
    </div>
  );
}

/* ---------- Variant A: left rail on the page ---------- */

function RailRow({ t, active, onOpen, rename, remove }: {
  t: MockThread; active: boolean; onOpen: () => void; rename: Common['rename']; remove: Common['remove'];
}) {
  const [editing, setEditing] = useState(false);
  return (
    <li
      onClick={onOpen}
      className={`group cursor-pointer rounded-md px-3 py-2 ${active ? 'bg-primary-surface' : 'hover:bg-surface-raised'}`}
    >
      <div className="flex items-start justify-between gap-2">
        <TitleOrEditor thread={t} editing={editing} setEditing={setEditing} rename={rename}
          className={`line-clamp-2 text-[12px] leading-snug ${active ? 'font-semibold text-ink' : 'text-ink-2'}`} />
        <span className={active ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}>
          <RowActions thread={t} remove={remove} onEditing={setEditing} />
        </span>
      </div>
      <div className="mt-0.5 text-[10px] text-ink-placeholder">
        {t.turns.length} {t.turns.length === 1 ? 'turn' : 'turns'} · {relative(lastAskedAt(t))}
      </div>
    </li>
  );
}

export function VariantA({ cards, resume, threads, rename, remove }: Common) {
  const [openId, setOpenId] = useState<string | null>(threads[0]?.id ?? null);
  const [q, setQ] = useState('');
  const open = threads.find(t => t.id === openId);
  const groups = useMemo(() => {
    const g: Record<string, MockThread[]> = {};
    threads.filter(t => matches(t, q)).forEach(t => { (g[bucket(lastAskedAt(t))] ||= []).push(t); });
    return Object.entries(g);
  }, [threads, q]);

  return (
    <div className="mx-auto grid min-h-[calc(100vh-var(--topbar-height))] max-w-[1080px] grid-cols-[250px_1fr] gap-8 px-8 py-10">
      <aside className="flex flex-col gap-4 border-r border-line-subtle pr-5">
        <button type="button" className={`${NEW_BTN} justify-center`} onClick={() => setOpenId(null)}>New thread</button>
        {threads.length > 0 && <SearchBox value={q} onChange={setQ} />}
        {threads.length === 0 ? (
          <p className="text-[12px] leading-relaxed text-ink-placeholder">
            No threads yet. Your first question starts one, and it will be here when you come back.
          </p>
        ) : (
          <nav className="flex flex-col gap-4">
            {groups.map(([label, ts]) => (
              <div key={label} className="flex flex-col gap-1">
                <div className="px-3 text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">{label}</div>
                <ul className="flex flex-col gap-0.5">
                  {ts.map(t => (
                    <RailRow key={t.id} t={t} active={t.id === openId} onOpen={() => setOpenId(t.id)} rename={rename} remove={remove} />
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        )}
        <div className="mt-auto flex items-center gap-2 text-[10px] text-ink-placeholder">
          <PencilIcon /> rename · <TrashIcon /> delete <DayOne />
        </div>
      </aside>

      <main className="flex max-w-[720px] flex-col gap-8">
        <Header />
        {open ? (
          <OpenThread thread={open} cards={cards} resume={resume} onNew={() => setOpenId(null)} />
        ) : (
          <>
            <Composer />
            {threads.length === 0 && <Starters />}
          </>
        )}
      </main>
    </div>
  );
}

/* ---------- Variant B: a separate list page with per-thread URLs ---------- */

function ListRow({ t, onOpen, rename, remove }: {
  t: MockThread; onOpen: () => void; rename: Common['rename']; remove: Common['remove'];
}) {
  const [editing, setEditing] = useState(false);
  const situation = firstSituation(t);
  return (
    <li onClick={onOpen} className="group grid cursor-pointer grid-cols-[1fr_auto] items-start gap-4 border-b border-line-subtle px-2 py-4 hover:bg-surface-raised">
      <div className="flex min-w-0 flex-col gap-1">
        <TitleOrEditor thread={t} editing={editing} setEditing={setEditing} rename={rename}
          className="text-[14px] font-semibold leading-snug text-ink" />
        <p className="line-clamp-1 text-[12px] text-ink-2">
          {t.turns[t.turns.length - 1].response.outcome === 'answered'
            ? (t.turns[t.turns.length - 1].response as { answer: string }).answer
            : (t.turns[t.turns.length - 1].response as { message: string }).message}
        </p>
        <div className="flex flex-wrap items-center gap-x-2 text-[11px] text-ink-placeholder">
          {situation && <span className="font-medium text-ink-2">{scenarioLabel(situation)}</span>}
          {situation && <span aria-hidden="true">·</span>}
          <span>{t.turns.length} {t.turns.length === 1 ? 'turn' : 'turns'}</span>
          <span aria-hidden="true">·</span>
          <span>last asked {relative(lastAskedAt(t)).toLowerCase()}</span>
        </div>
      </div>
      <span className="opacity-40 group-hover:opacity-100">
        <RowActions thread={t} remove={remove} onEditing={setEditing} />
      </span>
    </li>
  );
}

export function VariantB({ cards, resume, threads, rename, remove }: Common) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [q, setQ] = useState('');
  const open = threads.find(t => t.id === openId);
  const url = open ? `/ask-naren/threads/${open.id}` : asking ? '/ask-naren' : '/ask-naren/threads';

  return (
    <div className="mx-auto flex min-h-[calc(100vh-var(--topbar-height))] max-w-[760px] flex-col gap-8 px-8 py-10">
      <div className="font-mono text-[10px] text-ink-placeholder">(would be at {url})</div>
      {open || asking ? (
        <>
          <button type="button" onClick={() => { setOpenId(null); setAsking(false); }}
            className="inline-flex w-fit items-center gap-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-2 hover:text-primary">
            <ChevronLeftIcon /> All threads
          </button>
          <Header sub={open ? <p className="text-[15px] font-semibold text-ink">{deriveTitle(open)}</p> : undefined} />
          {open ? (
            <OpenThread thread={open} cards={cards} resume={resume} onNew={() => { setOpenId(null); setAsking(true); }} />
          ) : (
            <Composer />
          )}
        </>
      ) : (
        <>
          <header className="flex flex-col gap-2">
            <div className="flex items-start justify-between gap-4">
              <h1 className="text-2xl font-bold tracking-[-0.01em] text-ink">Your threads</h1>
              <button type="button" onClick={() => setAsking(true)}
                className="inline-flex h-9 shrink-0 items-center rounded-sm border border-primary px-4 text-[11px] font-bold uppercase tracking-[0.03em] text-primary hover:bg-primary hover:text-white">
                Ask Naren
              </button>
            </div>
            <p className="text-sm leading-relaxed text-ink-2">
              Every question you have asked, newest first. Only you can see these.
            </p>
          </header>
          {threads.length === 0 ? (
            <div className="flex flex-col gap-4 rounded-md border border-dashed border-line px-6 py-8">
              <p className="text-[15px] text-ink">You have not asked Naren anything yet.</p>
              <p className="text-[13px] leading-relaxed text-ink-2">
                Describe a live client situation and you will get back what Naren said when he faced the
                closest thing to it. Each question you ask starts a thread that stays here.
              </p>
              <button type="button" onClick={() => setAsking(true)}
                className="inline-flex h-9 w-fit items-center rounded-sm border border-primary px-4 text-[11px] font-bold uppercase tracking-[0.03em] text-primary hover:bg-primary hover:text-white">
                Ask your first question
              </button>
              <Starters />
            </div>
          ) : (
            <>
              <SearchBox value={q} onChange={setQ} wide />
              <ul className="flex flex-col border-t border-line-subtle">
                {threads.filter(t => matches(t, q)).map(t => (
                  <ListRow key={t.id} t={t} onOpen={() => setOpenId(t.id)} rename={rename} remove={remove} />
                ))}
              </ul>
              <div className="flex items-center gap-2 text-[10px] text-ink-placeholder">
                Row actions: <PencilIcon /> rename · <TrashIcon /> delete <DayOne />
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

/* ---------- Variant C: today's page + a compact recent-threads dropdown ---------- */

export function VariantC({ cards, resume, threads, remove }: Common) {
  const [openId, setOpenId] = useState<string | null>(threads[0]?.id ?? null);
  const [menu, setMenu] = useState(false);
  const open = threads.find(t => t.id === openId);
  const recent = threads.slice(0, 5);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-var(--topbar-height))] max-w-[720px] flex-col gap-8 px-8 py-10">
      <Header
        right={
          <div className="relative flex shrink-0 items-center gap-2">
            {threads.length > 0 && (
              <button type="button" onClick={() => setMenu(m => !m)} className={`${NEW_BTN} gap-1.5`} aria-expanded={menu}>
                Recent threads <ChevronDownIcon />
              </button>
            )}
            {open && <button type="button" className={NEW_BTN} onClick={() => { setOpenId(null); setMenu(false); }}>New thread</button>}
            {menu && (
              <div className="absolute right-0 top-10 z-20 w-[340px] rounded-md border border-line bg-surface p-2 shadow-lg">
                <ul className="flex flex-col">
                  {recent.map(t => (
                    <li key={t.id}>
                      <button type="button" onClick={() => { setOpenId(t.id); setMenu(false); }}
                        className={`flex w-full flex-col gap-0.5 rounded-sm px-3 py-2 text-left hover:bg-surface-raised ${t.id === openId ? 'bg-primary-surface' : ''}`}>
                        <span className="line-clamp-1 text-[12px] text-ink">{deriveTitle(t)}</span>
                        <span className="text-[10px] text-ink-placeholder">{relative(lastAskedAt(t))} · {t.turns.length} {t.turns.length === 1 ? 'turn' : 'turns'}</span>
                      </button>
                    </li>
                  ))}
                </ul>
                <div className="mt-1 flex items-center justify-between border-t border-line-subtle px-3 pt-2 text-[10px] text-ink-placeholder">
                  <span>Last 5 only. No search, no rename.</span>
                  {open && (
                    <button type="button" className="flex items-center gap-1 hover:text-error" onClick={() => { remove(open.id); setOpenId(null); setMenu(false); }}>
                      <TrashIcon /> delete open thread <DayOne />
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        }
      />
      {open ? (
        <OpenThread thread={open} cards={cards} resume={resume} onNew={() => setOpenId(null)} />
      ) : (
        <>
          <Composer />
          {threads.length === 0 && <Starters />}
        </>
      )}
    </div>
  );
}

/* ---------- signed-out: how /login sits in front of all three ---------- */

export function SignedOut() {
  const FIELD = 'w-full rounded-md border border-line bg-surface px-4 py-2.5 text-sm text-ink placeholder:text-ink-placeholder';
  const LABEL = 'text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder';
  return (
    <div className="mx-auto flex min-h-[calc(100vh-var(--topbar-height))] max-w-[400px] flex-col justify-center gap-8 px-8 py-10">
      <div className="font-mono text-[10px] text-ink-placeholder">(copy of the real /login?next=/ask-naren — already built in #44; same for every variant)</div>
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-[-0.01em] text-ink">Sign in</h1>
        <p className="text-sm leading-relaxed text-ink-2">Ask Naren keeps your threads under your Joveo email.</p>
      </header>
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5"><span className={LABEL}>Email</span><input className={FIELD} placeholder="you@joveo.com" /></div>
        <div className="flex flex-col gap-1.5"><span className={LABEL}>Password</span><input type="password" className={FIELD} /></div>
        <button type="button" className="inline-flex h-9 items-center justify-center rounded-sm border border-primary px-4 text-[11px] font-bold uppercase tracking-[0.03em] text-primary">Sign in</button>
      </div>
      <p className="text-[11px] leading-relaxed text-ink-placeholder">
        Not set up yet, or forgot your password? Ask the Ask Naren admin — passwords are set by them, not reset by email.
      </p>
      <p className="rounded-md border border-dashed border-line px-4 py-3 text-[11px] leading-relaxed text-ink-placeholder">
        Open for #39: on success you land back on /ask-naren. In A and C that opens your most recent thread; in B it
        lands on the list. Which should the first screen after sign-in be?
      </p>
    </div>
  );
}

/* ---------- root ---------- */

export function ThreadsPrototype({ variant, cards, state, resume }: {
  variant: string; cards: Cards; state: PState; resume: Resume;
}) {
  const [threads, setThreads] = useState<MockThread[]>(THREADS);
  const shown = state === 'empty' ? [] : threads;
  const common: Common = {
    cards, resume, threads: shown,
    rename: (id, title) => setThreads(ts => ts.map(t => (t.id === id ? { ...t, customTitle: title } : t))),
    remove: id => setThreads(ts => ts.filter(t => t.id !== id)),
  };
  if (state === 'signed-out') return <SignedOut />;
  // key on state so switching empty <-> threads resets which thread is open
  if (variant === 'B') return <VariantB key={state} {...common} />;
  if (variant === 'C') return <VariantC key={state} {...common} />;
  return <VariantA key={state} {...common} />;
}
