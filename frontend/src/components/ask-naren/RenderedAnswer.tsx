import type { AskNarenRendered } from '@/types';

import { scenarioLabel } from '@/lib/thread';

/**
 * An answer built from stored rows, with no model call behind it (issues #19, #20).
 *
 * STYLED AS REFERENCE, NOT AS COACHING. An `answered` response is Naren's guidance
 * paraphrased and quote-verified; this is the corpus describing itself — what is covered,
 * what comes up most, the real exchange, how it continued. Rendering the two identically
 * would suggest a list of topics carries the same kind of authority as a grounded answer.
 *
 * NO QUOTE BLOCK ANYWHERE, because there is nothing to verify: nothing was generated, so
 * nothing can have been invented. The accent border that marks a verified quote on
 * `AnswerCard` is deliberately absent here — it means "this was checked", and reusing it
 * where nothing was checked would erode what it signals.
 *
 * A SWITCH ON `kind` WITH A `never` DEFAULT, for the same reason the outcome switch has one:
 * a sixth rendered kind is a build failure here rather than a blank area on the page.
 */

const SHELL = 'flex flex-col gap-5 rounded-md border border-line bg-surface p-6';
const EYEBROW =
  'text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder';

/** The real client turn and Naren's reply, verbatim. Used by two kinds. */
function Exchange({ clientSaid, narenReplied }: { clientSaid: string; narenReplied: string }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <span className={EYEBROW}>Client said</span>
        <p className="text-[13px] leading-relaxed text-ink-2">{clientSaid}</p>
      </div>
      <div className="flex flex-col gap-1">
        <span className={EYEBROW}>Naren replied</span>
        <p className="text-[13px] leading-relaxed text-ink">{narenReplied}</p>
      </div>
    </div>
  );
}

function Source({ label }: { label: string }) {
  return (
    <footer className="flex flex-wrap items-baseline gap-x-2 border-t border-line-subtle pt-4 text-[11px] text-ink-placeholder">
      <span className="font-semibold uppercase tracking-[0.06em]">Source</span>
      <span className="break-all font-medium text-ink-2">{label}</span>
    </footer>
  );
}

export function RenderedAnswer({ result }: { result: AskNarenRendered }) {
  switch (result.kind) {
    case 'discovery':
      return (
        <article className={SHELL}>
          <header className="flex flex-col gap-1">
            <span className={EYEBROW}>What Ask Naren covers</span>
            <p className="text-[13px] text-ink-2">
              {result.total} situations drawn from Naren&rsquo;s real calls.
            </p>
          </header>
          <div className="flex flex-col gap-5">
            {result.topics.map(topic => (
              <div key={topic.topic} className="flex flex-col gap-2">
                <h3 className="text-[11px] font-bold uppercase tracking-[0.06em] text-ink">
                  {topic.topic}
                </h3>
                <ul className="flex flex-col gap-2 border-l border-line-subtle pl-4">
                  {topic.scenarios.map(s => (
                    <li key={s.scenario_key} className="flex flex-col gap-0.5">
                      <span className="text-[13px] font-medium text-ink">
                        {scenarioLabel(s.scenario_key)}
                      </span>
                      {s.description && (
                        <span className="text-[12px] leading-relaxed text-ink-2">
                          {s.description}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </article>
      );

    case 'frequency':
      return (
        <article className={SHELL}>
          <header className="flex flex-col gap-1">
            <span className={EYEBROW}>What comes up most</span>
            {/* Printed as the service wrote it. Composing this sentence here would put the
                same qualifier in two places, and it is the qualifier that stops "most
                common" being read as a fact about clients rather than about the corpus. */}
            <p className="text-[12px] leading-relaxed text-ink-2">{result.basis}</p>
          </header>
          <ol className="flex flex-col gap-3">
            {result.scenarios.map((s, i) => (
              <li key={s.scenario_key} className="flex items-baseline gap-3">
                <span className="w-5 shrink-0 text-[11px] tabular-nums text-ink-placeholder">
                  {i + 1}
                </span>
                <div className="flex flex-1 flex-col gap-0.5">
                  <span className="text-[13px] font-medium text-ink">
                    {scenarioLabel(s.scenario_key)}
                  </span>
                  {s.description && (
                    <span className="text-[12px] leading-relaxed text-ink-2">{s.description}</span>
                  )}
                </div>
                <span className="shrink-0 text-[11px] tabular-nums text-ink-placeholder">
                  {s.support_calls} calls
                </span>
              </li>
            ))}
          </ol>
        </article>
      );

    case 'show_exchange':
      return (
        <article className={SHELL}>
          <span className={EYEBROW}>The real exchange</span>
          <Exchange
            clientSaid={result.exchange.client_said}
            narenReplied={result.exchange.naren_replied}
          />
          <Source label={result.citation.label} />
        </article>
      );

    case 'what_happened_next':
      return (
        <article className={SHELL}>
          <span className={EYEBROW}>How the conversation went on</span>
          <Exchange
            clientSaid={result.exchange.client_said}
            narenReplied={result.exchange.naren_replied}
          />
          {result.is_last ? (
            <p className="border-l-2 border-line pl-4 text-[12px] italic text-ink-placeholder">
              Nothing followed this in the call.
            </p>
          ) : (
            <div className="flex flex-col gap-4 border-l-2 border-line pl-4">
              <span className={EYEBROW}>Then</span>
              {result.following.map((f, i) => (
                <Exchange key={i} clientSaid={f.client_said} narenReplied={f.naren_replied} />
              ))}
            </div>
          )}
          <Source label={result.citation.label} />
        </article>
      );

    case 'coverage_check':
      return (
        <article className={SHELL}>
          <header className="flex flex-col gap-1">
            <span className={EYEBROW}>Coverage</span>
            <p className="text-[13px] leading-relaxed text-ink">
              The closest thing Ask Naren covers to{' '}
              <span className="font-medium">&ldquo;{result.asked_about}&rdquo;</span> is{' '}
              <span className="font-medium">{scenarioLabel(result.nearest.scenario_key)}</span>,
              drawn from {result.nearest.support_calls} of Naren&rsquo;s calls.
            </p>
          </header>
          {result.nearest.description && (
            <p className="border-l-2 border-line pl-4 text-[12px] leading-relaxed text-ink-2">
              {result.nearest.description}
            </p>
          )}
          {/* Deliberately NOT phrased as a decline. A CSM asking "do you cover this" needs to
              tell "nothing here" apart from "you asked it wrong", and this intent exists to
              separate them -- so it always answers, and points at the next move. */}
          <p className="text-[11px] text-ink-placeholder">
            Describe a specific client situation and Ask Naren will answer from the closest
            real exchange.
          </p>
          <Source label={result.citation.label} />
        </article>
      );

    default: {
      const unhandled: never = result;
      throw new Error(`unhandled rendered kind: ${JSON.stringify(unhandled)}`);
    }
  }
}
