'use client';

import { useId, useState } from 'react';

import { CopyButton } from './CopyButton';
import * as api from './threadClient';

type Rating = 'good' | 'bad';

/**
 * The row under a reply: Copy, and a good / bad rating with an optional "why" (migration
 * 0003). Like Claude's rating prompt: the thumb is saved on click, so a rating is never lost
 * to a skipped box; the reason, if written, replaces it a moment later.
 *
 * Both directions ask why. Good answers matter as much as bad ones: they are what an engine
 * change is tested against, so it does not break what already works.
 *
 * `target` is null for a reply that is not stored (#40's "not saved" turn): there is nothing
 * to attach a rating to, so only Copy is offered.
 */
export function TurnActions({
  copyText,
  target,
}: {
  copyText: string | null;
  target: { threadId: number; position: number } | null;
}) {
  const [rating, setRating] = useState<Rating | null>(null);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fieldId = useId();

  if (!copyText && !target) return null;

  const save = async (next: Rating, why: string | null) => {
    if (!target) return false;
    const r = await api.sendFeedback(target.threadId, target.position, next, why);
    if (r.kind === 'ok') return true;
    setNote(
      r.kind === 'signed_out'
        ? 'Your sign-in ended, so that was not saved. Sign in again to rate answers.'
        : 'Could not save that just now. Try again in a moment.',
    );
    return false;
  };

  const rate = async (next: Rating) => {
    setRating(next);
    setOpen(true);
    setReason('');
    setNote(null);
    await save(next, null);
  };

  const send = async () => {
    if (!rating) return;
    setBusy(true);
    const ok = await save(rating, reason.trim() || null);
    setBusy(false);
    if (ok) {
      setOpen(false);
      setNote('Thanks — that helps.');
    }
  };

  const thumb = (kind: Rating) =>
    `flex h-10 w-10 items-center justify-center rounded-md transition-colors duration-fast ease-out-quart ${
      rating === kind ? 'bg-primary-surface text-primary' : 'text-ink-2 hover:bg-surface-raised hover:text-ink'
    }`;

  return (
    <div className="mt-3 flex flex-col gap-3">
      <div className="-ml-2.5 flex flex-wrap items-center gap-1">
        {copyText && <CopyButton text={copyText} />}
        {target && (
          <>
            <button type="button" aria-label="Good answer" aria-pressed={rating === 'good'} title="Good answer" onClick={() => rate('good')} className={thumb('good')}>
              <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M7 11v9H4v-9h3zM7 11l4-7a2 2 0 0 1 2 2v4h5.5a2 2 0 0 1 2 2.3l-1.2 6A2 2 0 0 1 17.3 20H7" /></svg>
            </button>
            <button type="button" aria-label="Bad answer" aria-pressed={rating === 'bad'} title="Bad answer" onClick={() => rate('bad')} className={thumb('bad')}>
              <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 13V4h3v9h-3zM17 13l-4 7a2 2 0 0 1-2-2v-4H5.5a2 2 0 0 1-2-2.3l1.2-6A2 2 0 0 1 6.7 4H17" /></svg>
            </button>
          </>
        )}
        <span role="status" className="ml-1.5 text-[13px] text-ink-2">{note}</span>
      </div>

      {open && rating && (
        <section aria-label="Tell us why" className="flex max-w-[68ch] flex-col gap-2.5 rounded-xl border border-line bg-bg p-4 shadow-low">
          <div className="flex items-center justify-between gap-3">
            <label htmlFor={fieldId} className="text-[14px] font-semibold text-ink">
              {rating === 'good' ? 'What made this answer good?' : 'What was wrong with this answer?'}
            </label>
            <button type="button" aria-label="Close" onClick={() => setOpen(false)} className="flex h-8 w-8 items-center justify-center rounded-md text-ink-2 hover:bg-surface-raised hover:text-ink">
              <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
            </button>
          </div>
          <textarea
            id={fieldId}
            rows={3}
            maxLength={2000}
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder={rating === 'good' ? 'e.g. I could send it to the client as it was' : 'e.g. It answered a different question than the one I asked'}
            className="resize-y rounded-md border border-line bg-surface px-3 py-2 text-[14px] leading-relaxed text-ink placeholder:text-ink-placeholder focus:border-primary focus:outline-none"
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-[12.5px] text-ink-2">Optional. Your rating is already saved.</span>
            <div className="flex gap-2">
              <button type="button" onClick={() => setOpen(false)} className="h-9 rounded-md border border-line bg-bg px-3 text-[13px] font-semibold text-ink hover:bg-surface-raised">
                Skip
              </button>
              <button type="button" disabled={busy} onClick={send} className="h-9 rounded-md bg-primary px-4 text-[13px] font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
                {busy ? 'Sending…' : 'Send'}
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
