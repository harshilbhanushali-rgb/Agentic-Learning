'use client';

import type { AskNarenResponse } from '@/types';

import { useState } from 'react';

import { SituationForm } from '@/components/ask-naren/SituationForm';
import { AnswerCard } from '@/components/ask-naren/AnswerCard';
import { DeclineNotice } from '@/components/ask-naren/DeclineNotice';

/**
 * Ask Naren (issue #3). One input, three outcomes: asking, answered, declined.
 *
 * NO `useMode()` CALL, DELIBERATELY. The page must render identically in Veteran and Newbie
 * mode, and not branching is the only implementation of that which cannot drift. Every
 * other page in the app branches; this one is the exception on purpose.
 *
 * The asked situation is COMMITTED on submit -- shown above the response and cleared from
 * the input -- so a CSM can type an unrelated situation immediately without clearing
 * anything first, while still seeing what the answer on screen was answering.
 */
type Phase =
  | { kind: 'idle' }
  | { kind: 'asking'; asked: string }
  | { kind: 'answered'; asked: string; result: AskNarenResponse }
  | { kind: 'failed'; asked: string };

export default function AskNarenPage() {
  const [draft, setDraft] = useState('');
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });

  const ask = async () => {
    const asked = draft.trim();
    if (!asked) return;
    setPhase({ kind: 'asking', asked });
    setDraft('');
    try {
      const res = await fetch('/api/ask-naren', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ situation: asked }),
      });
      // The service returns a decline-shaped body even on its own 503, so a non-OK status
      // is still worth parsing before treating anything as a failure.
      const result = (await res.json()) as AskNarenResponse;
      if (typeof result?.declined !== 'boolean') throw new Error('unrecognised response');
      setPhase({ kind: 'answered', asked, result });
    } catch {
      // Reached only when the service is unreachable or answered with something that is not
      // its contract. Issue #6 turns this into a proper decline-shaped explanation; until
      // then it is a plain line rather than a broken page.
      setPhase({ kind: 'failed', asked });
    }
  };

  return (
    // min-h matches workspace/ and simulator/: the app shell's sidebar is viewport-tall,
    // so a short page leaves it cut off above the fold.
    <div className="mx-auto flex min-h-[calc(100vh-var(--topbar-height))] max-w-[720px] flex-col gap-8 px-8 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-[-0.01em] text-ink">Ask Naren</h1>
        <p className="text-sm leading-relaxed text-ink-2">
          Describe a live client situation. You get back the answer Naren gave when he faced
          the closest thing to it, with the call it came from.
        </p>
      </header>

      <SituationForm
        value={draft}
        onChange={setDraft}
        onSubmit={ask}
        busy={phase.kind === 'asking'}
      />

      {phase.kind !== 'idle' && (
        <section className="flex flex-col gap-4" aria-live="polite" aria-busy={phase.kind === 'asking'}>
          <div className="flex flex-col gap-1.5 border-l-2 border-line pl-4">
            <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
              You asked
            </span>
            <p className="text-[13px] leading-relaxed text-ink-2">{phase.asked}</p>
          </div>

          {phase.kind === 'asking' && (
            <div className="flex items-center gap-3 rounded-md border border-line-subtle bg-surface-raised px-6 py-5">
              <span
                className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent"
                aria-hidden="true"
              />
              <span className="text-[13px] text-ink-2">
                Searching Naren&rsquo;s calls for the closest exchange&hellip;
              </span>
            </div>
          )}

          {phase.kind === 'answered' && (
            phase.result.declined
              ? <DeclineNotice result={phase.result} />
              : <AnswerCard result={phase.result} />
          )}

          {phase.kind === 'failed' && (
            <div className="rounded-md border border-dashed border-line bg-surface-raised p-6 text-sm leading-relaxed text-ink-2">
              Ask Naren could not be reached. Nothing was answered &mdash; this is a fault on
              our side, not a &ldquo;no close match&rdquo;. Try again in a moment.
            </div>
          )}
        </section>
      )}
    </div>
  );
}
