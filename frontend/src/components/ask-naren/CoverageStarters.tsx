/**
 * The empty state for a user with no threads (#39): where Naren's calls go deepest, so a
 * first question is not a surprise decline.
 *
 * DRAWN FROM `ask-naren/docs/findings/corpus-is-onboarding-not-escalation.md`, which measured
 * the twelve most-supported situations: eleven are about getting a client contracted,
 * integrated and live, one about a running campaign's performance. The list is the top of
 * that ranking, in its order; the closing line says plainly which ground is thin, because a
 * guide that implies even coverage sets a CSM up to conclude the tool is broken the first
 * time it declines on the question they cared about most (the finding's point 5).
 *
 * If the corpus changes, re-run `frequency` and change this list with the finding.
 */
const DEEPEST = [
  ['Contracts and legal review', 'an MSA in redlines, legal holding up the start'],
  ['Budget allocation and testing', 'agreeing a first budget, splitting it across test markets'],
  ['XML feed setup', 'a job feed moving over from another vendor'],
  ['ATS integration and API mapping', 'how long the integration takes on the client’s side'],
  ['Landing pages and conversion setup', 'getting the apply flow ready before launch'],
  ['Dashboard access and reporting', 'who can see what, and what the reports show'],
] as const;

export function CoverageStarters() {
  return (
    <section className="flex flex-col gap-3 rounded-md border border-line-subtle bg-surface-raised px-6 py-5">
      <h2 className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
        Where Naren&rsquo;s calls go deepest
      </h2>
      <ul className="flex flex-col gap-2">
        {DEEPEST.map(([situation, example]) => (
          <li key={situation} className="text-[13px] leading-relaxed text-ink-2">
            <span className="font-medium text-ink">{situation}</span>
            <span className="text-ink-placeholder"> — {example}</span>
          </li>
        ))}
      </ul>
      <p className="text-[11px] leading-relaxed text-ink-placeholder">
        Mostly getting clients contracted, integrated and live. Questions about rescuing a
        campaign that is already running &mdash; spend pacing, applicant quality falling off
        &mdash; are declined more often, because there is less of that on record.
      </p>
    </section>
  );
}
