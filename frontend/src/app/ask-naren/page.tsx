'use client';

import type { AskNarenDecline, AskNarenResponse } from '@/types';

import { useState } from 'react';

import { SituationForm } from '@/components/ask-naren/SituationForm';
import { AnswerCard } from '@/components/ask-naren/AnswerCard';
import { DeclineNotice } from '@/components/ask-naren/DeclineNotice';
import { ClarifyPrompt } from '@/components/ask-naren/ClarifyPrompt';

/**
 * Ask Naren (issue #3). One input; the response is answered, declined or clarify (#13).
 *
 * NO `useMode()` CALL, DELIBERATELY. The page must render identically in Veteran and Newbie
 * mode, and not branching is the only implementation of that which cannot drift. Every
 * other page in the app branches; this one is the exception on purpose.
 *
 * The asked situation is COMMITTED on submit -- shown above the response and cleared from
 * the input -- so a CSM can type an unrelated situation immediately without clearing
 * anything first, while still seeing what the answer on screen was answering.
 *
 * THERE IS NO ERROR STATE (issue #6). The proxy answers every request with either an answer
 * or a decline-SHAPED body, including when the service is unreachable, so an outage renders
 * through the same DeclineNotice as a genuine no-match. One render path cannot drift out of
 * sync with itself, and there is no state this page can reach holding neither an answer nor
 * an explanation. UNREACHABLE below is the last resort for the proxy ITSELF being gone --
 * a bug rather than an expected path, but still not a reason to show a CSM a broken page.
 */
type Phase =
  | { kind: 'idle' }
  | { kind: 'asking'; asked: string }
  | { kind: 'answered'; asked: string; result: AskNarenResponse };

const UNREACHABLE: AskNarenDecline = {
  outcome: 'declined',
  reason: 'service_unreachable',
  message:
    'Ask Naren could not be reached just now. Nothing was answered — this is a fault on ' +
    'our side, not a "no close match". Try again in a moment.',
};

/** The `outcome` values the service can send. Guards `ask` against a body that parsed as
 *  JSON but is not this contract -- a proxy or a crashed worker returning something else. */
const OUTCOMES = new Set<AskNarenResponse['outcome']>(['answered', 'declined', 'clarify']);

/**
 * The one place a response's `outcome` is turned into a component.
 *
 * A SWITCH WITH AN EXHAUSTIVENESS CHECK, not a ternary. `never` in the default branch means
 * adding a fourth outcome to the union is a BUILD failure here rather than a blank area on
 * the page at runtime -- which is the whole reason the contract discriminates on one key.
 * `npm run build` is the only gate this frontend has, so it has to be the thing that catches
 * it.
 */
function Outcome({ result }: { result: AskNarenResponse }) {
  switch (result.outcome) {
    case 'answered':
      return <AnswerCard result={result} />;
    case 'declined':
      return <DeclineNotice result={result} />;
    case 'clarify':
      return <ClarifyPrompt result={result} />;
    default: {
      const unhandled: never = result;
      throw new Error(`unhandled outcome: ${JSON.stringify(unhandled)}`);
    }
  }
}

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
      // A non-OK status still carries the contract: the service's own fault is a 503 with a
      // decline body, and so is the proxy's unreachable response. Status is not the signal.
      const result = (await res.json()) as AskNarenResponse;
      if (!OUTCOMES.has(result?.outcome)) throw new Error('unrecognised response');
      setPhase({ kind: 'answered', asked, result });
    } catch {
      // The proxy itself did not answer -- the app is down, not the service. Rendered as a
      // decline like any other so the CSM still gets a sentence rather than a dead screen.
      setPhase({ kind: 'answered', asked, result: UNREACHABLE });
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

          {phase.kind === 'answered' && <Outcome result={phase.result} />}
        </section>
      )}
    </div>
  );
}
