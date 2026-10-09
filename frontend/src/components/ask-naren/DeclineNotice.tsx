import type { AskNarenDecline, AskNarenDeclineReason } from '@/types';

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
 * THE HEADING AND THE HINT BRANCH ON `reason` (issues #6, #14, #32); the STYLING never
 * does. Every decline reaches this component -- including an outage, which the proxy
 * deliberately shapes as a decline so the page needs no error branch. Four situations need
 * different advice, and giving the wrong one sends a CSM chasing something that cannot
 * work:
 *
 *   - a fault: the question was fine, the tool is down, rewording is pointless;
 *   - out of scope: rewording is pointless for a different reason -- the answer is not in
 *     Naren's calls to find, however it is phrased;
 *   - a genuine no-match: rewording IS the useful next move;
 *   - BUSY (issue #32): nothing is wrong with either the question or the tool, and the
 *     useful next move is simply to ask the same thing again in a moment. It is the one
 *     decline where retrying verbatim is the right advice, which is why it needs its own
 *     words -- reading "try describing the situation in the client's own words" here would
 *     send a CSM rewriting a question that was fine.
 *
 * THE STYLING STILL DOES NOT BRANCH, even though busy is not really a decline at all. The
 * words are what a CSM reads and they say plainly that this is a queue rather than a
 * refusal; giving it its own border or colour would be the first crack in the rule that
 * keeps a fault from eventually looking scarier than a no-match. `message` carries the
 * estimate ("ask again in about 30 seconds"), composed by the service, so the retry
 * suggestion is concrete without this file knowing the arithmetic.
 *
 * Both strings come from one table keyed by reason rather than from nested ternaries, so a
 * new reason is one entry and cannot end up with a heading from one branch and a hint from
 * another. Verified by deletion: removing the `service_busy` entry fails `npm run build`
 * with "Property 'service_busy' is missing", so a future reason cannot quietly inherit
 * another one's advice.
 */

/** One entry per decline reason: what to head it, and what to suggest next. Exhaustive over
 *  `AskNarenDeclineReason`, so adding a reason to that union is a build failure here rather
 *  than a decline that silently renders as a no-match. */
const COPY: Record<AskNarenDeclineReason, { heading: string; hint: string }> = {
  no_close_match: {
    heading: 'No grounded answer',
    hint: 'Try describing the situation in the client’s own words, or the specific question you need to answer.',
  },
  grounding_unverified: {
    heading: 'No grounded answer',
    hint: 'Try describing the situation in the client’s own words, or the specific question you need to answer.',
  },
  out_of_scope: {
    heading: 'Outside what Naren’s calls cover',
    hint: 'Rewording will not help here. Try a product owner or the docs for this one — Ask Naren only knows what Naren said on calls.',
  },
  follow_up_ungrounded: {
    heading: 'Not in that call',
    // The one decline whose useful next move is to ASK AGAIN, differently. A follow-up runs
    // no search at all — it is answered from the call the previous answer came from — so
    // this says Naren did not cover it THERE, not that nothing close exists anywhere.
    hint: 'Ask it as a fresh question, in the client’s own words, and Ask Naren will search his calls for a closer moment.',
  },
  service_error: {
    heading: 'Ask Naren is unavailable',
    hint: 'Nothing you typed caused this, and rewording it will not help. The answer you asked for is not lost — ask again once it is back.',
  },
  service_unreachable: {
    heading: 'Ask Naren is unavailable',
    hint: 'Nothing you typed caused this, and rewording it will not help. The answer you asked for is not lost — ask again once it is back.',
  },
  service_busy: {
    // NOT "unavailable". Busy and down read identically to a CSM if we let them, and then
    // the tool looks broken every lunchtime. The estimate itself lives in `message`.
    heading: 'Ask Naren is busy',
    hint: 'Your question was fine and nothing is broken — several people are asking at once. Ask the same thing again in a moment and it will go through.',
  },
  deadline_exceeded: {
    heading: 'Ask Naren ran out of time',
    hint: 'It stopped rather than leave you waiting. Nothing you typed caused this — ask the same thing again.',
  },
  store_unavailable: {
    // #40. NOT "unavailable": the service may be perfectly healthy -- what failed is the
    // store behind sign-in and threads, so nothing was asked at all. The page has put the
    // question back in the box and added nothing to the thread, and the hint says so.
    heading: 'Ask Naren can’t reach your threads',
    hint: 'Nothing you typed caused this, and rewording it will not help. Your question has not been sent — send it again in a moment.',
  },
};

export function DeclineNotice({ result }: { result: AskNarenDecline }) {
  const { heading, hint } = COPY[result.reason];

  return (
    <article className="flex flex-col gap-2 rounded-md border border-dashed border-line bg-surface-raised p-6">
      <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
        {heading}
      </div>
      <p className="text-sm leading-relaxed text-ink-2">{result.message}</p>
      <p className="mt-1 text-[11px] text-ink-placeholder">{hint}</p>
    </article>
  );
}
