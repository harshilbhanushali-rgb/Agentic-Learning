import type { AskNarenAnswer } from '@/types';

import { scenarioLabel } from '@/lib/thread';

/**
 * An answered response: the guidance, then the verbatim line of Naren's it rests on, then
 * the situation it is about and the call it came from.
 *
 * The quote is shown, not hidden behind a disclosure. The service verified it verbatim
 * against the cited call before sending (the grounding gate), and that verification is the
 * reason to trust the answer -- putting the evidence one click away would leave a CSM
 * reading an assertion. Same reasoning as ADR 0002 on unredacted citations.
 *
 * THE SCENARIO IS NAMED (issue #16). In a thread a scenario identifier is inherited from
 * one message to the next, so a CSM who moves to a different client without saying so can
 * be given answers that are grounded, coherent and about the wrong situation. Nothing
 * server-side can catch that -- the answer looks correct from the inside. Naming the
 * scenario is what puts it in front of the one person who knows.
 */
export function AnswerCard({ result }: { result: AskNarenAnswer }) {
  return (
    <article className="flex flex-col gap-5 rounded-md border border-line bg-surface p-6">
      <p className="text-[15px] leading-relaxed text-ink whitespace-pre-line">{result.answer}</p>

      <blockquote className="border-l-2 border-accent pl-4">
        <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
          What Naren actually said
        </div>
        <p className="mt-1.5 text-[13px] italic leading-relaxed text-ink-2">
          &ldquo;{result.quote}&rdquo;
        </p>
      </blockquote>

      <footer className="flex flex-col gap-1.5 border-t border-line-subtle pt-4 text-[11px] text-ink-placeholder">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="font-semibold uppercase tracking-[0.06em]">Situation</span>
          <span className="font-medium text-ink-2">
            {scenarioLabel(result.citation.scenario_key)}
          </span>
        </div>
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="font-semibold uppercase tracking-[0.06em]">Source</span>
          {/* Raw filename for now. Issue #4 resolves `label` to an account and a date; this
              renders whatever the service put in `label`, so that lands with no change here. */}
          <span className="break-all font-medium text-ink-2">{result.citation.label}</span>
        </div>
      </footer>
    </article>
  );
}
