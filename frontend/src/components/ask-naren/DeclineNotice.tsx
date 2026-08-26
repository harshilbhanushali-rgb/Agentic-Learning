import type { AskNarenDecline } from '@/types';

/**
 * A decline. Rendered as a plain, composed explanation -- NOT as an error, and not styled
 * like one: declining is Ask Naren working correctly. The tool answers only from Naren's
 * real calls, so "nothing close enough exists" is a legitimate outcome and a CSM reading it
 * should feel informed, not blocked.
 *
 * `message` is printed as the service wrote it. Composing a sentence from `reason` here
 * would put the same explanation in two places, and the service's copy is the one that
 * knows why it declined.
 */
export function DeclineNotice({ result }: { result: AskNarenDecline }) {
  return (
    <article className="flex flex-col gap-2 rounded-md border border-dashed border-line bg-surface-raised p-6">
      <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
        No grounded answer
      </div>
      <p className="text-sm leading-relaxed text-ink-2">{result.message}</p>
      <p className="mt-1 text-[11px] text-ink-placeholder">
        Try describing the situation in the client&rsquo;s own words, or the specific question
        you need to answer.
      </p>
    </article>
  );
}
