'use client';

import type { ThreadSummaryJson } from '@/lib/thread';

import { useEffect, useId, useRef, useState } from 'react';

import { PencilIcon, PlusIcon, TrashIcon } from '@/components/icons';
import { groupByBucket, relativeTime } from '@/components/ask-naren/threadTime';

/**
 * The thread rail (#39, variant A): the signed-in user's own threads beside the question
 * box, grouped Today / Yesterday / This week / This month / Earlier, newest first.
 *
 * Titles are the first question unless renamed; rename is inline. "Remove from your list"
 * says exactly what the soft delete does (#37) -- the thread leaves this list, and nothing
 * is described as erased, because it is not.
 *
 * `now` is null until the page has mounted: the groups and "2 hours ago" are in the reader's
 * own time zone, which the server render does not know, so the list waits one frame rather
 * than render something the browser would immediately contradict.
 */
export function ThreadRail({
  threads,
  activeId,
  now,
  stale,
  onOpen,
  onNew,
  onRename,
  onRemove,
}: {
  threads: ThreadSummaryJson[];
  activeId: number | null;
  now: Date | null;
  /** The last refresh failed, so this list may be behind. */
  stale: boolean;
  onOpen: (id: number) => void;
  onNew: () => void;
  onRename: (id: number, title: string | null) => Promise<boolean>;
  onRemove: (id: number) => Promise<boolean>;
}) {
  return (
    <aside
      aria-label="Your threads"
      className="flex flex-col gap-4 border-b border-line-subtle pb-6 md:border-b-0 md:border-r md:pb-0 md:pr-5"
    >
      <button
        type="button"
        onClick={onNew}
        // Always present. Moving to an unrelated situation is exactly when a carried
        // scenario would strand an answer, so the way out has to be visible.
        className="inline-flex h-8 items-center justify-center gap-1.5 rounded-sm border border-line px-3 text-[11px] font-bold uppercase tracking-[0.03em] text-ink-2 transition-colors duration-fast ease-out-quart hover:border-primary hover:text-primary"
      >
        <PlusIcon /> New thread
      </button>

      {threads.length === 0 ? (
        <p className="px-1 text-[12px] leading-relaxed text-ink-placeholder">
          No threads yet. Your first question starts one, and it stays here for you to come
          back to. Only you can see your threads.
        </p>
      ) : now ? (
        <nav className="flex flex-col gap-4">
          {groupByBucket(threads, t => new Date(t.lastTurnAt), now).map(group => (
            <div key={group.label} className="flex flex-col gap-1">
              <h2 className="px-3 text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
                {group.label}
              </h2>
              <ul className="flex flex-col gap-0.5">
                {group.items.map(t => (
                  <RailRow
                    key={t.id}
                    thread={t}
                    active={t.id === activeId}
                    now={now}
                    onOpen={() => onOpen(t.id)}
                    onRename={title => onRename(t.id, title)}
                    onRemove={() => onRemove(t.id)}
                  />
                ))}
              </ul>
            </div>
          ))}
        </nav>
      ) : (
        <div className="h-24" aria-hidden="true" />
      )}

      {stale && (
        <p className="px-1 text-[11px] leading-relaxed text-ink-placeholder">
          Could not refresh this list just now, so it may be out of date.
        </p>
      )}
    </aside>
  );
}

const ICON_BUTTON =
  'rounded-sm p-1 text-ink-placeholder transition-colors duration-fast ease-out-quart hover:bg-surface-raised hover:text-ink focus-visible:text-ink';

function RailRow({
  thread,
  active,
  now,
  onOpen,
  onRename,
  onRemove,
}: {
  thread: ThreadSummaryJson;
  active: boolean;
  now: Date;
  onOpen: () => void;
  onRename: (title: string | null) => Promise<unknown>;
  onRemove: () => Promise<boolean>;
}) {
  const [mode, setMode] = useState<'view' | 'rename' | 'confirm'>('view');
  const [busy, setBusy] = useState(false);

  const turns = `${thread.turnCount} ${thread.turnCount === 1 ? 'turn' : 'turns'}`;

  return (
    <li
      className={`group rounded-md ${active ? 'bg-primary-surface' : 'hover:bg-surface-raised'}`}
    >
      {mode === 'rename' ? (
        <RenameField
          initial={thread.title}
          busy={busy}
          onCancel={() => setMode('view')}
          onSave={async title => {
            // Back to the title either way: on a failure the page says why, and the title
            // shown is still the stored one.
            setBusy(true);
            await onRename(title);
            setBusy(false);
            setMode('view');
          }}
        />
      ) : (
        <div className="flex items-start gap-1 px-3 py-2">
          <button
            type="button"
            onClick={onOpen}
            aria-current={active ? 'true' : undefined}
            className="flex min-w-0 flex-1 flex-col gap-0.5 text-left focus-visible:outline-none"
          >
            <span
              className={`line-clamp-2 text-[12px] leading-snug ${active ? 'font-semibold text-ink' : 'text-ink-2 group-hover:text-ink'}`}
            >
              {thread.title}
            </span>
            <span className="text-[10px] text-ink-placeholder">
              {turns} · {relativeTime(new Date(thread.lastTurnAt), now)}
            </span>
          </button>
          <span
            className={`flex shrink-0 items-center gap-0.5 ${active || mode === 'confirm' ? 'opacity-100' : 'opacity-0 focus-within:opacity-100 group-hover:opacity-100'}`}
          >
            <button type="button" className={ICON_BUTTON} aria-label={`Rename “${thread.title}”`} title="Rename" onClick={() => setMode('rename')}>
              <PencilIcon />
            </button>
            <button type="button" className={ICON_BUTTON} aria-label={`Remove “${thread.title}” from your list`} title="Remove from your list" onClick={() => setMode('confirm')}>
              <TrashIcon />
            </button>
          </span>
        </div>
      )}

      {mode === 'confirm' && (
        <div
          role="group"
          aria-label="Confirm removal"
          className="mx-2 mb-2 flex flex-col gap-2 rounded-md border border-line bg-surface p-3 text-[11px] leading-relaxed text-ink-2"
        >
          <span>Remove this thread from your list? You will not be able to open it again.</span>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                const ok = await onRemove();
                setBusy(false);
                if (!ok) setMode('view');
              }}
              className="whitespace-nowrap rounded-sm border border-error px-2 py-1 font-semibold text-error transition-colors duration-fast ease-out-quart hover:bg-error-surface disabled:opacity-60"
            >
              Remove from your list
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setMode('view')}
              className="whitespace-nowrap rounded-sm border border-line px-2 py-1 transition-colors duration-fast ease-out-quart hover:border-ink-placeholder"
            >
              Keep it
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

/** Enter saves, Escape cancels, blur saves. An empty title clears the rename back to the
 *  first question -- the store derives it again. */
function RenameField({
  initial,
  busy,
  onSave,
  onCancel,
}: {
  initial: string;
  busy: boolean;
  onSave: (title: string | null) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const ref = useRef<HTMLInputElement>(null);
  const done = useRef(false);
  const id = useId();

  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);

  const save = () => {
    if (done.current) return;
    done.current = true;
    const title = value.trim();
    if (title === initial.trim()) onCancel();
    else onSave(title || null);
  };

  return (
    <div className="px-2 py-1.5">
      <label className="sr-only" htmlFor={id}>Thread title</label>
      <input
        id={id}
        ref={ref}
        value={value}
        maxLength={120}
        disabled={busy}
        onChange={e => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={e => {
          if (e.key === 'Enter') {
            e.preventDefault();
            save();
          } else if (e.key === 'Escape') {
            e.preventDefault();
            done.current = true;
            onCancel();
          }
        }}
        className="w-full rounded-sm border border-primary bg-surface px-2 py-1 text-[12px] text-ink focus:outline-none"
      />
      <span className="mt-1 block px-0.5 text-[10px] text-ink-placeholder">
        Enter to save · Esc to cancel · empty to use the first question
      </span>
    </div>
  );
}
