import type { AskNarenAnswer } from '@/types';

import { scenarioLabel } from '@/lib/thread';

import { answerBlocks } from './answerBlocks';
import { boldSpans } from './boldSpans';
import { CopyButton } from './CopyButton';
import { plainAnswer } from './plainAnswer';

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
    <div className="flex max-w-[68ch] flex-col gap-3 text-[16px] leading-[1.7] text-ink">
      {answerBlocks(text).map((block, i) => {
        switch (block.kind) {
          case 'heading':
            return (
              <h3 key={i} className="mt-2 text-[16px] font-semibold text-ink first:mt-0">
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
    // CHAT LAYOUT (2026-11-10, Vignesh: "close to Claude"): the answer is plain text, not a
    // card. The quote stays on the page, in its own box, for the reason above.
    <article className="flex flex-col gap-4">
      {result.my_reply && (
        <div className="flex flex-col gap-1">
          <span className="text-[13px] font-semibold text-ink-2">What you replied</span>
          <p className="text-[14px] leading-relaxed text-ink-2">{result.my_reply}</p>
        </div>
      )}

      <AnswerBody text={result.answer} />

      <figure className="flex flex-col gap-2 rounded-[14px] border border-line bg-surface px-[18px] py-3.5">
        <figcaption className="text-[13px] font-semibold text-primary">
          What Naren said on the call
        </figcaption>
        <blockquote className="text-[14.5px] leading-relaxed text-ink">
          &ldquo;{result.quote}&rdquo;
        </blockquote>
        <dl className="flex flex-col gap-1 text-[12.5px] leading-relaxed text-ink-2">
          <div className="flex flex-wrap gap-x-1.5">
            <dt>Topic:</dt>
            <dd className="font-medium text-ink">{scenarioLabel(result.citation.scenario_key)}</dd>
          </div>
          <div className="flex flex-wrap gap-x-1.5">
            <dt>Call:</dt>
            {/* Raw filename for now. Issue #4 resolves `label` to an account and a date; this
                renders whatever the service put in `label`, so that lands with no change here. */}
            <dd className="break-all font-medium text-ink">{result.citation.label}</dd>
          </div>
          {result.drawn_from && result.drawn_from.length > 1 && (
            <div className="flex flex-wrap gap-x-1.5">
              <dt>Drawn from {result.drawn_from.length} calls:</dt>
              <dd className="font-medium text-ink">
                {result.drawn_from.map((call) => call.label).join(' · ')}
              </dd>
            </div>
          )}
        </dl>
      </figure>

      <div className="-ml-2.5">
        <CopyButton text={plainAnswer(result.answer)} />
      </div>
    </article>
  );
}
