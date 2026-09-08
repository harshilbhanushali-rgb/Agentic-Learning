'use client';

import type { AskNarenDecline, AskNarenResponse } from '@/types';
import type { ThreadTurn } from '@/lib/thread';

import { useEffect, useRef, useState } from 'react';

import { SituationForm } from '@/components/ask-naren/SituationForm';
import { AnswerCard } from '@/components/ask-naren/AnswerCard';
import { DeclineNotice } from '@/components/ask-naren/DeclineNotice';
import { ClarifyPrompt } from '@/components/ask-naren/ClarifyPrompt';
import { RenderedAnswer } from '@/components/ask-naren/RenderedAnswer';
import { load, save, scenarioLabel, trimThread, turnFrom } from '@/lib/thread';

/**
 * Ask Naren (issue #3). One input; the response is answered, declined or clarify (#13),
 * and the conversation continues in a thread (#15).
 *
 * NO `useMode()` CALL, DELIBERATELY. The page must render identically in Veteran and Newbie
 * mode, and not branching is the only implementation of that which cannot drift. Every
 * other page in the app branches; this one is the exception on purpose.
 *
 * THE PAGE HOLDS THE THREAD. The service stores nothing — it reads Postgres once at startup
 * and closes the connection before serving a request, so it has nowhere to keep a
 * conversation. The thread is replayed with each message and persisted to `localStorage`,
 * the pattern already used for mode and theme. See `@/lib/thread`.
 *
 * THERE IS NO ERROR STATE (issue #6). The proxy answers every request with either an answer
 * or a decline-SHAPED body, including when the service is unreachable, so an outage renders
 * through the same DeclineNotice as a genuine no-match. One render path cannot drift out of
 * sync with itself, and there is no state this page can reach holding neither an answer nor
 * an explanation. UNREACHABLE below is the last resort for the proxy ITSELF being gone —
 * a bug rather than an expected path, but still not a reason to show a CSM a broken page.
 */
type Phase =
  | { kind: 'idle' }
  | { kind: 'asking'; asked: string }
  | { kind: 'answered'; result: AskNarenResponse };

const UNREACHABLE: AskNarenDecline = {
  outcome: 'declined',
  reason: 'service_unreachable',
  message:
    'Ask Naren could not be reached just now. Nothing was answered — this is a fault on ' +
    'our side, not a "no close match". Try again in a moment.',
};

/** The `outcome` values the service can send. Guards `ask` against a body that parsed as
 *  JSON but is not this contract -- a proxy or a crashed worker returning something else. */
const OUTCOMES = new Set<AskNarenResponse['outcome']>([
  'answered', 'declined', 'clarify', 'rendered',
]);

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
    case 'rendered':
      return <RenderedAnswer result={result} />;
    default: {
      const unhandled: never = result;
      throw new Error(`unhandled outcome: ${JSON.stringify(unhandled)}`);
    }
  }
}

/** What the CSM typed, above whatever came back. */
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

/**
 * A past exchange, replayed from the thread.
 *
 * PLAINER THAN THE LIVE ANSWER, and that is a consequence of what a thread stores rather
 * than a style choice. A turn keeps the answer's text and the IDENTIFIERS of the call it
 * rested on — not the verified quote, which is text from Naren's calls and deliberately
 * does not travel in the thread (ADR 0006, and issue #16's quote bleed). So an answer read
 * back after a reload shows what was said and which call it came from, and the quote lives
 * on the live response only.
 */
function PastTurn({ turn }: { turn: ThreadTurn }) {
  return (
    <div className="flex flex-col gap-3">
      <Asked message={turn.message} />
      <div className="rounded-md border border-line-subtle bg-surface-raised px-6 py-4">
        <p className="text-[13px] leading-relaxed text-ink-2 whitespace-pre-line">{turn.reply}</p>
        {turn.call_filename && (
          <p className="mt-3 break-all border-t border-line-subtle pt-3 text-[11px] text-ink-placeholder">
            {/* The scenario is named here for the same reason it is on a live answer: a
                thread inherits a scenario identifier, and a CSM scrolling back is the only
                one who can see that three answers ago it stopped being about their client. */}
            {scenarioLabel(turn.scenario_key)} · {turn.call_filename}
          </p>
        )}
      </div>
    </div>
  );
}

export default function AskNarenPage() {
  const [draft, setDraft] = useState('');
  const [turns, setTurns] = useState<ThreadTurn[]>([]);
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });

  // Which thread the answer coming back belongs to. A request takes ~12s, and "New thread"
  // is reachable throughout: without this, the resolving `ask` closes over the turns as
  // they were at submit time and RESURRECTS the conversation the CSM just cleared, one
  // answer heavier. Bumping the id is what makes clearing win.
  const threadId = useRef(0);

  // Hydrated in an effect rather than in the initial state, because `localStorage` does not
  // exist during the server render and reading it there would make the first client render
  // disagree with the HTML React just received.
  useEffect(() => { setTurns(load()); }, []);

  const ask = async () => {
    const asked = draft.trim();
    if (!asked) return;
    const askedIn = threadId.current;
    setPhase({ kind: 'asking', asked });
    setDraft('');

    let result: AskNarenResponse;
    try {
      const res = await fetch('/api/ask-naren', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // TRIMMED, not truncated: a long conversation is shrunk by dropping old PROSE and
        // never a carried identifier, because the message that established the scenario is
        // usually the first one (ADR 0006). Without this the body eventually exceeds the
        // service's cap and every further question 400s.
        body: JSON.stringify({ situation: asked, thread: trimThread(turns) }),
      });
      // A non-OK status still carries the contract: the service's own fault is a 503 with a
      // decline body, and so is the proxy's unreachable response. Status is not the signal.
      const body = (await res.json()) as AskNarenResponse;
      if (!OUTCOMES.has(body?.outcome)) throw new Error('unrecognised response');
      result = body;
    } catch {
      // The proxy itself did not answer -- the app is down, not the service. Rendered as a
      // decline like any other so the CSM still gets a sentence rather than a dead screen.
      result = UNREACHABLE;
    }

    // The CSM started a fresh thread while this was in flight. They have moved on, so the
    // answer is dropped rather than appended to a conversation it does not belong to --
    // and a stale carried identifier is exactly what starting fresh was for.
    if (askedIn !== threadId.current) return;

    // Recorded even when it was an outage. A CSM scrolling back should see that they asked
    // and what happened, and issue #16 needs a decline in the thread to be visible for the
    // same reason a clarify is.
    const next = [...turns, turnFrom(asked, result)];
    setTurns(next);
    save(next);
    setPhase({ kind: 'answered', result });
  };

  const startNewThread = () => {
    threadId.current += 1;
    setTurns([]);
    save([]);
    setPhase({ kind: 'idle' });
    setDraft('');
  };

  // The rich rendering of the most recent answer — its verified quote and resolved citation
  // — exists only for this page load. After a reload the same exchange renders as a
  // PastTurn, because a thread carries identifiers rather than Naren's text.
  const live = phase.kind === 'answered' ? phase.result : undefined;

  return (
    // min-h matches workspace/ and simulator/: the app shell's sidebar is viewport-tall,
    // so a short page leaves it cut off above the fold.
    <div className="mx-auto flex min-h-[calc(100vh-var(--topbar-height))] max-w-[720px] flex-col gap-8 px-8 py-10">
      <header className="flex flex-col gap-2">
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-2xl font-bold tracking-[-0.01em] text-ink">Ask Naren</h1>
          {turns.length > 0 && (
            <button
              type="button"
              onClick={startNewThread}
              // Present whenever there is a thread to clear. Moving to an unrelated
              // situation is exactly when a carried scenario would strand an answer, so
              // the way out has to be visible rather than a reload.
              className="inline-flex h-8 shrink-0 items-center rounded-sm border border-line px-3 text-[11px] font-bold uppercase tracking-[0.03em] text-ink-2 transition-colors duration-fast ease-out-quart hover:border-primary hover:text-primary"
            >
              New thread
            </button>
          )}
        </div>
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

      {(turns.length > 0 || phase.kind === 'asking') && (
        <section
          className="flex flex-col gap-8"
          aria-live="polite"
          aria-busy={phase.kind === 'asking'}
        >
          {turns.map((turn, i) => {
            const isLatest = i === turns.length - 1;
            return (
              <div key={i} className="flex flex-col gap-4">
                {isLatest && live ? (
                  <>
                    <Asked message={turn.message} />
                    <Outcome result={live} />
                  </>
                ) : (
                  <PastTurn turn={turn} />
                )}
              </div>
            );
          })}

          {phase.kind === 'asking' && (
            <div className="flex flex-col gap-4">
              <Asked message={phase.asked} />
              <div className="flex items-center gap-3 rounded-md border border-line-subtle bg-surface-raised px-6 py-5">
                <span
                  className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent"
                  aria-hidden="true"
                />
                <span className="text-[13px] text-ink-2">
                  Searching Naren&rsquo;s calls for the closest exchange&hellip;
                </span>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
