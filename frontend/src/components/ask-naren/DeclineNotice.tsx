import type { AskNarenDecline } from '@/types';

/**
 * A decline. Rendered as a plain, composed explanation -- NOT as an error, and not styled
 * like one: declining is usually Ask Naren working correctly. The tool answers only from
 * Naren's real calls, so "nothing close enough exists" is a legitimate outcome and a CSM
 * reading it should feel informed, not blocked.
 *
 * `message` is printed as the service wrote it. Composing a sentence from `reason` here
 * would put the same explanation in two places, and the service's copy is the one that
 * knows why it declined.
 *
 * ONE THING DOES BRANCH ON `reason` (issue #6): the follow-up hint. Every decline reaches
 * this component -- including an outage, which the proxy deliberately shapes as a decline so
 * the page needs no error branch. But "try rewording the situation" is useless advice when
 * the service is unreachable, and telling a CSM mid-call to rephrase while the tool is down
 * would send them chasing a problem that is not theirs. The styling stays identical; only
 * the suggestion changes.
 */

/** The reasons that mean something broke, rather than the tool declining on purpose. */
const FAULTS = new Set(['service_error', 'service_unreachable']);

export function DeclineNotice({ result }: { result: AskNarenDecline }) {
  const isFault = FAULTS.has(result.reason);

  return (
    <article className="flex flex-col gap-2 rounded-md border border-dashed border-line bg-surface-raised p-6">
      <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
        {isFault ? 'Ask Naren is unavailable' : 'No grounded answer'}
      </div>
      <p className="text-sm leading-relaxed text-ink-2">{result.message}</p>
      <p className="mt-1 text-[11px] text-ink-placeholder">
        {isFault
          ? 'Nothing you typed caused this, and rewording it will not help. The answer you asked for is not lost — ask again once it is back.'
          : 'Try describing the situation in the client’s own words, or the specific question you need to answer.'}
      </p>
    </article>
  );
}
