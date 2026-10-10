import type { AskNarenResponse } from '@/types';

import { AnswerCard } from '@/components/ask-naren/AnswerCard';
import { DeclineNotice } from '@/components/ask-naren/DeclineNotice';
import { ClarifyPrompt } from '@/components/ask-naren/ClarifyPrompt';
import { RenderedAnswer } from '@/components/ask-naren/RenderedAnswer';

/**
 * The one place a response's `outcome` is turned into a component.
 *
 * A SWITCH WITH AN EXHAUSTIVENESS CHECK, not a ternary. `never` in the default branch means
 * adding a fifth outcome to the union is a BUILD failure here rather than a blank area on
 * the page at runtime -- which is the whole reason the contract discriminates on one key.
 * `npm run build` is the only gate this frontend has, so it has to be the thing that catches
 * it.
 *
 * EVERY TURN RENDERS THROUGH IT, OLD OR NEW (#39). A stored turn keeps the service's
 * response verbatim (#37), so a thread reopened days later shows the same card it showed
 * live -- verified quote, citation and all. The reduced `PastTurn` this replaces existed only
 * because the browser-held thread kept identifiers and not the response.
 */
export function Outcome({ result }: { result: AskNarenResponse }) {
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

/** What the CSM typed, above whatever came back: a bubble on the right, as in a chat. */
export function Asked({ message, when }: { message: string; when?: string }) {
  return (
    <div className="flex flex-col items-end gap-1">
      <span className="px-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
        You asked{when ? <span className="font-normal normal-case tracking-normal"> · {when}</span> : null}
      </span>
      <p className="max-w-[85%] whitespace-pre-line rounded-2xl rounded-tr-md bg-primary-surface px-4 py-2.5 text-[14px] leading-relaxed text-ink">
        {message}
      </p>
    </div>
  );
}

/**
 * The answer is real but it is in no thread (#40): the service answered and the turn write
 * failed, twice. Said under the answer rather than instead of it -- a store hiccup must not
 * cost a CSM the answer on their screen -- and the next question starts a fresh thread, so a
 * follow-up is never answered from a thread with a gap where this turn should be.
 */
export function NotSavedNote() {
  return (
    <p className="border-l-2 border-warning pl-4 text-[11px] leading-relaxed text-ink-2">
      <span className="font-semibold text-ink">Not saved to this thread.</span>{' '}
      Ask Naren replied, but the reply could not be stored, so it will not be here when you
      come back. Your next question starts a new thread, so nothing is answered from a thread
      with a gap in it.
    </p>
  );
}
