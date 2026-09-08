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
 * THE ACCENT BORDER APPEARS ON EXACTLY ONE KIND, `phrasing`. On `AnswerCard` it means "this
 * quote was checked", and reusing it where nothing was checked would erode what it signals.
 * A `signature_language` entry is phrase-and-quote one-to-one, so every quote shown there is
 * covered — which is the one place the border still means what it means everywhere else.
 * `pitfalls` shows quotes too and deliberately uses the plain border instead: the pitfall
 * text beside them is our sentence, not Naren's.
 *
 * EVERY QUOTE CARRIES ITS SOURCE. These are Naren's verbatim words from a real client call,
 * and ADR 0002's argument for unredacted citations is that a citation is what makes an
 * answer trustworthy rather than a bare assertion — which needs the call named. The three
 * kinds with nothing quotable (`sequence`, `scenario_check`, `play_confidence`) carry no
 * source because there is no single call behind them.
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

function ScenarioLine({ scenario }: { scenario: { scenario_key: string; description: string } }) {
  return (
    <li className="flex flex-col gap-0.5">
      <span className="text-[13px] font-medium text-ink">
        {scenarioLabel(scenario.scenario_key)}
      </span>
      {scenario.description && (
        <span className="text-[12px] leading-relaxed text-ink-2">{scenario.description}</span>
      )}
    </li>
  );
}

/** The source line under one verbatim quote (issue #18). Lighter than `Source`, which is a
 *  card footer — these repeat once per quote, and a full bordered footer between every
 *  phrase would read as a list of separators rather than of phrases. */
function QuoteSource({ label }: { label: string }) {
  return (
    <cite className="not-italic text-[11px] text-ink-placeholder">
      <span className="font-semibold uppercase tracking-[0.06em]">Source</span>{' '}
      <span className="break-all font-medium text-ink-2">{label}</span>
    </cite>
  );
}

/** The header every playbook-derived answer carries: what kind of thing this is, and which
 *  scenario's play it came from. The scenario line is not decoration — three of these five
 *  answers have no citation at all, so it is the only thing that lets a CSM catch a
 *  misroute. */
function Play({ kind, scenarioKey }: { kind: string; scenarioKey: string }) {
  return (
    <header className="flex flex-col gap-1">
      <span className={EYEBROW}>{kind}</span>
      <p className="text-[12px] text-ink-2">
        For <span className="font-medium">{scenarioLabel(scenarioKey)}</span>
      </p>
    </header>
  );
}

function Stat({ n, label }: { n: number; label: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xl font-bold tabular-nums text-ink">{n}</span>
      <span className="text-[11px] text-ink-placeholder">{label}</span>
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
          {/* FLAT WHEN THE GROUPING IS NOT REAL. Every scenario on the live taxonomy
              carries `primary_topic = 'ungrouped'`, so grouping would put all 34 under one
              invented heading — which tells a CSM the tool is disorganised rather than that
              one field was never populated. The grouped branch is correct the day it is. */}
          {result.grouped ? (
            <div className="flex flex-col gap-5">
              {result.topics.map(topic => (
                <div key={topic.topic} className="flex flex-col gap-2">
                  <h3 className="text-[11px] font-bold uppercase tracking-[0.06em] text-ink">
                    {topic.topic}
                  </h3>
                  <ul className="flex flex-col gap-2 border-l border-line-subtle pl-4">
                    {topic.scenarios.map(s => (
                      <ScenarioLine key={s.scenario_key} scenario={s} />
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ) : (
            <ul className="flex flex-col gap-2.5">
              {result.scenarios.map(s => (
                <ScenarioLine key={s.scenario_key} scenario={s} />
              ))}
            </ul>
          )}
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
            {/* PHRASED AS "NEAREST", NEVER AS "YES". Retrieval returns a nearest exchange
                for any string at all, so "the closest thing we cover is X" reads as
                confirmation even when the CSM's topic is absent entirely — which is the
                confusion this intent exists to end. Ask Naren cannot say "we do not cover
                that" either: ADR 0005 measured cosine as unable to separate right answers
                from wrong ones, so there is no honest threshold. What it can do is show the
                nearest situation and how much sits behind it, and let the CSM judge. */}
            <p className="text-[13px] leading-relaxed text-ink">
              The nearest situation Ask Naren has to{' '}
              <span className="font-medium">&ldquo;{result.asked_about}&rdquo;</span> is{' '}
              <span className="font-medium">{scenarioLabel(result.nearest.scenario_key)}</span>
              {result.nearest.evidence === 'thin' ? (
                <>
                  , and its evidence is <span className="font-medium">thin</span> — just{' '}
                  {result.nearest.support_calls}{' '}
                  {result.nearest.support_calls === 1 ? 'call' : 'calls'}.
                </>
              ) : (
                <>, drawn from {result.nearest.support_calls} of Naren&rsquo;s calls.</>
              )}
            </p>
            <p className="text-[12px] leading-relaxed text-ink-2">
              Judge for yourself whether that is what you meant — it is the closest match,
              not a confirmation that your situation is covered.
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

    /* -- the Layer C playbook, rendered (issue #18). Each carries a SCENARIO line, because
          none of them has a citation: they show the play, derived from many calls, so there
          is no single call to point at — and the scenario is then the only thing that makes
          a misroute visible. */
    case 'sequence':
      return (
        <article className={SHELL}>
          <Play kind="The order Naren runs it in" scenarioKey={result.scenario_key} />
          <ol className="flex flex-col gap-2">
            {result.steps.map((step, i) => (
              <li key={i} className="flex items-baseline gap-3">
                <span className="w-5 shrink-0 text-[11px] tabular-nums text-ink-placeholder">
                  {i + 1}
                </span>
                <span className="text-[13px] leading-relaxed text-ink">{step}</span>
              </li>
            ))}
          </ol>
        </article>
      );

    case 'phrasing':
      return (
        <article className={SHELL}>
          <Play kind="How Naren words it" scenarioKey={result.scenario_key} />
          <div className="flex flex-col gap-5">
            {result.phrases.map((p, i) => (
              <div key={i} className="flex flex-col gap-1.5">
                <span className="text-[13px] font-medium text-ink">
                  &ldquo;{p.phrase}&rdquo;
                </span>
                {/* The accent border IS used here, unlike everywhere else in this file: a
                    phrase and the quote it came from are one-to-one, so this really is
                    Naren&rsquo;s own verbatim line rather than a rendering of our summary. */}
                <blockquote className="flex flex-col gap-1.5 border-l-2 border-accent pl-4">
                  <p className="text-[12px] italic leading-relaxed text-ink-2">{p.quote}</p>
                  <QuoteSource label={p.label} />
                </blockquote>
              </div>
            ))}
          </div>
        </article>
      );

    case 'pitfalls':
      return (
        <article className={SHELL}>
          <Play kind="What usually goes wrong" scenarioKey={result.scenario_key} />
          <div className="flex flex-col gap-5">
            {result.pitfalls.map((p, i) => (
              <div key={i} className="flex flex-col gap-1.5">
                <p className="text-[13px] leading-relaxed text-ink">{p.text}</p>
                {p.evidence.map((e, j) => (
                  <blockquote key={j} className="flex flex-col gap-1.5 border-l-2 border-line pl-4">
                    <p className="text-[12px] italic leading-relaxed text-ink-2">{e.quote}</p>
                    <QuoteSource label={e.label} />
                  </blockquote>
                ))}
              </div>
            ))}
          </div>
        </article>
      );

    case 'scenario_check':
      return (
        <article className={SHELL}>
          <Play kind="When this play applies" scenarioKey={result.scenario_key} />
          <p className="text-[13px] leading-relaxed text-ink">{result.applies_when}</p>
          {/* NO VERDICT, deliberately. Whether the play fits a live client is a judgement
              Ask Naren has only the CSM's own sentence for; claiming it would be exactly
              the confident-and-wrong answer a catch-all scenario produces. */}
          <p className="text-[12px] leading-relaxed text-ink-2">
            You asked about &ldquo;{result.asked_about}&rdquo;. Compare that with the above
            &mdash; Ask Naren cannot tell from one sentence whether it is the same situation.
          </p>
        </article>
      );

    case 'where_else_seen':
      return (
        <article className={SHELL}>
          {/* THE SCENARIO IS NAMED, like every other answer that retrieves (#12 story 10).
              It matters more here: this answer names no single call, so the situation is
              the only thing that can give a misroute away. */}
          <header className="flex flex-col gap-1">
            <span className={EYEBROW}>Where else this has come up</span>
            <p className="text-[12px] text-ink-2">
              You asked about &ldquo;{result.asked_about}&rdquo; &mdash; nearest situation{' '}
              <span className="font-medium text-ink">
                {scenarioLabel(result.scenario_key)}
              </span>
            </p>
          </header>

          {/* A RANGE, NOT A COUNT. Each call whose client is not recorded unambiguously
              could be a new account or one already listed, so stating a single number
              would assert one end of that as fact.

              The floor is `accounts_at_least`, NOT `accounts_named` — with no participant
              sidecars nothing can be named and `accounts_named` is 0, but exchanges that
              exist came from somebody. "Between 0 and 3 accounts" is impossible. */}
          <p className="text-[13px] leading-relaxed text-ink">
            {result.accounts_at_least === result.accounts_at_most ? (
              <>
                <span className="font-medium">{result.accounts_at_least}</span>{' '}
                {result.accounts_at_least === 1 ? 'account' : 'accounts'}
              </>
            ) : (
              <>
                Between <span className="font-medium">{result.accounts_at_least}</span> and{' '}
                <span className="font-medium">{result.accounts_at_most}</span> accounts
              </>
            )}
            , across {result.exchanges}{' '}
            {result.exchanges === 1 ? 'exchange' : 'exchanges'}
            {/* Not every nearby exchange is about the same situation — the top-20
                neighbourhood measures at ~6/20 same-situation. Saying so is what lets a CSM
                tell a real book-wide pattern from a wide, incoherent neighbourhood. */}
            {result.same_scenario < result.exchanges && (
              <>
                , of which{' '}
                <span className="font-medium">{result.same_scenario}</span>{' '}
                {result.same_scenario === 1 ? 'is' : 'are'} about that same situation
              </>
            )}
            .
          </p>

          <ul className="flex flex-col gap-2">
            {result.accounts.map((a, i) => (
              <li key={i} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                {a.named ? (
                  <span className="text-[13px] font-medium text-ink">{a.account}</span>
                ) : (
                  /* Rendered as the filename it is, muted and monospaced, so it never reads
                     as a client name. Naming it would be a guess; hiding it would
                     under-report how widely this comes up. */
                  <span className="break-all font-mono text-[11px] text-ink-placeholder">
                    {a.account}
                  </span>
                )}
                <span className="text-[12px] tabular-nums text-ink-2">
                  {a.exchanges} {a.exchanges === 1 ? 'exchange' : 'exchanges'}
                  {a.calls > 1 && ` · ${a.calls} calls`}
                </span>
              </li>
            ))}
          </ul>

          <p className="text-[12px] leading-relaxed text-ink-2">{result.basis}</p>
        </article>
      );

    case 'play_confidence':
      return (
        <article className={SHELL}>
          <Play kind="How well evidenced this play is" scenarioKey={result.scenario_key} />
          {/* MOVES AND QUOTES LEAD, and `n_evidence` deliberately does not. The first two
              are counted from the live document — what the play rests on today. The third
              is how many moments were CONSIDERED when it was built, capped by the builder's
              selection limit: measured 2026-09-09, 25 of 33 live playbooks sit exactly on
              that cap, and it inverts (a play showing 50 rests on 8 verified quotes; one
              showing 16 rests on 9). Rendered as the largest number it was the one thing on
              this card that carried no information. */}
          <div className="flex flex-wrap gap-x-8 gap-y-3">
            <Stat n={result.moves} label={result.moves === 1 ? 'move' : 'moves'} />
            <Stat n={result.quotes} label={result.quotes === 1 ? 'quote' : 'quotes'} />
          </div>
          <p className="text-[12px] leading-relaxed text-ink-2">
            Built from {result.n_evidence_capped ? 'at least ' : ''}
            <span className="font-medium text-ink">{result.n_evidence}</span> recorded
            moments
            {result.n_evidence_capped
              ? ' — the most the builder looks at, so the real number may be higher.'
              : '.'}
          </p>
          <p className="text-[12px] leading-relaxed text-ink-2">{result.basis}</p>
        </article>
      );

    default: {
      const unhandled: never = result;
      throw new Error(`unhandled rendered kind: ${JSON.stringify(unhandled)}`);
    }
  }
}
