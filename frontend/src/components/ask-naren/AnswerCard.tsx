import type { AskNarenAnswer } from '@/types';

import { scenarioLabel } from '@/lib/thread';

import { answerBlocks } from './answerBlocks';
import { boldSpans } from './boldSpans';

function Inline({ text }: { text: string }) {
  return (
    <>
      {boldSpans(text).map((span, i) =>
        span.bold ? <strong key={i} className="font-semibold">{span.text}</strong> : span.text,
      )}
    </>
  );
}

/** The answer as headings, lists and paragraphs (`answerBlocks`), all rendered as escaped text. */
function AnswerBody({ text }: { text: string }) {
  return (
    <div className="flex flex-col gap-3 text-[15px] leading-relaxed text-ink">
      {answerBlocks(text).map((block, i) => {
        switch (block.kind) {
          case 'heading':
            return (
              <h3 key={i} className="mt-2 text-[15px] font-semibold text-ink first:mt-0">
                <Inline text={block.text} />
              </h3>
            );
          case 'bullets':
            return (
              <ul key={i} className="flex list-disc flex-col gap-1.5 pl-5 marker:text-ink-placeholder">
                {block.items.map((item, j) => <li key={j}><Inline text={item} /></li>)}
              </ul>
            );
          case 'numbered':
            return (
              <ol key={i} className="flex list-decimal flex-col gap-1.5 pl-5 marker:text-ink-placeholder">
                {block.items.map((item, j) => <li key={j}><Inline text={item} /></li>)}
              </ol>
            );
          case 'rule':
            return <hr key={i} className="border-line-subtle" />;
          default:
            return (
              <p key={i} className="whitespace-pre-line">
                <Inline text={block.text} />
              </p>
            );
        }
      })}
    </div>
  );
}

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
 *
 * A CONTRAST (issue #21) IS THE SAME CARD WITH THE CSM'S OWN REPLY SHOWN FIRST. It is an
 * `answered` response with the same guarantee -- a model wrote it and the gate verified a
 * quote -- so it is not a different outcome and not a different component. What differs is
 * that the answer is a comparison, and a comparison needs both sides on the page.
 *
 * NOTHING HERE SAYS THE CSM WAS RIGHT OR WRONG, and the absence is the design. Judging a
 * reply against a standard needs Layer D's grader; what this has is one real moment where
 * Naren faced the same thing. So the CSM's reply is presented as a neutral quotation with
 * no tick, no cross and no score -- a verdict rendered here would be believed on the
 * strength of one retrieved exchange.
 */
export function AnswerCard({ result }: { result: AskNarenAnswer }) {
  return (
    <article className="flex flex-col gap-5 rounded-2xl rounded-tl-md border border-line-subtle bg-bg shadow-sm p-6">
      {result.my_reply && (
        <div className="flex flex-col gap-1">
          <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
            What you replied
          </span>
          <p className="text-[13px] leading-relaxed text-ink-2">{result.my_reply}</p>
        </div>
      )}

      <AnswerBody text={result.answer} />

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
        {result.drawn_from && result.drawn_from.length > 1 && (
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="font-semibold uppercase tracking-[0.06em]">
              Drawn from {result.drawn_from.length} calls
            </span>
            <span className="font-medium text-ink-2">
              {result.drawn_from.map((call) => call.label).join(' · ')}
            </span>
          </div>
        )}
      </footer>
    </article>
  );
}
