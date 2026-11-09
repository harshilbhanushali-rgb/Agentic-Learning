'use client';

import { useId, useState } from 'react';

/**
 * The empty page's starting points (#39, redesigned 2026-11-10): three topic chips, each
 * opening example questions that put the question in the box -- not send it -- so it can be
 * edited first.
 *
 * DRAWN FROM `ask-naren/docs/findings/corpus-is-onboarding-not-escalation.md`, which measured
 * the twelve most-supported situations: eleven are about getting a client contracted,
 * integrated and live, one about a running campaign's performance. Every example below sits
 * in that well-covered ground (tracking setup, ATS integration and feeds, budget, apply
 * flow, dashboard access), so a first question is not a surprise decline. The closing line
 * on the page says plainly which ground is thin (the finding's point 5).
 *
 * If the corpus changes, re-run `frequency` and change these with the finding.
 */
const TOPICS = [
  {
    key: 'tracking',
    title: 'Tracking',
    icon: <path d="M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm0 4.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z" />,
    questions: [
      'How does Joveo’s tracking work?',
      'What do we need from the client to set up tracking?',
      'Why don’t our numbers match the client’s ATS?',
    ],
  },
  {
    key: 'integration',
    title: 'Integration',
    icon: <path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0V8zM12 17v4" />,
    questions: [
      'How long does an ATS integration take on the client’s side?',
      'The client is moving their job feed over from another vendor',
      'Which ATS stages do we map?',
    ],
  },
  {
    key: 'campaign',
    title: 'Campaign setup',
    icon: <path d="M4 7h10M18 7h2M4 17h4M12 17h8M16 5v4M10 15v4" />,
    questions: [
      'How should the client split a first budget across test markets?',
      'Getting the apply flow ready before launch',
      'Who can see the dashboard, and what do the reports show?',
    ],
  },
] as const;

export function CoverageStarters({ onPick }: { onPick: (question: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const listId = useId();
  const topic = TOPICS.find(t => t.key === open);

  return (
    <section aria-label="Common questions" className="flex w-full flex-col gap-3">
      <div className="flex flex-wrap justify-center gap-2.5">
        {TOPICS.map(t => {
          const on = t.key === open;
          return (
            <button
              key={t.key}
              type="button"
              aria-expanded={on}
              aria-controls={on ? listId : undefined}
              onClick={() => setOpen(on ? null : t.key)}
              className={`inline-flex h-10 items-center gap-2 rounded-full border px-4 text-[14px] font-semibold text-ink transition-colors duration-fast ease-out-quart ${on ? 'border-primary bg-primary-surface' : 'border-line bg-bg hover:bg-surface-raised'}`}
            >
              <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className="text-primary">
                {t.icon}
              </svg>
              {t.title}
            </button>
          );
        })}
      </div>
      {topic && (
        <ul
          id={listId}
          aria-label={`${topic.title} questions`}
          className="flex flex-col gap-0.5 rounded-2xl border border-line bg-bg p-1.5"
        >
          {topic.questions.map(q => (
            <li key={q}>
              <button
                type="button"
                onClick={() => { onPick(q); setOpen(null); }}
                className="min-h-[44px] w-full rounded-md px-3.5 py-2.5 text-left text-[15px] text-ink transition-colors duration-fast ease-out-quart hover:bg-surface-raised"
              >
                {q}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
