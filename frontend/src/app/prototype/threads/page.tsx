import { Suspense } from 'react';

import { PrototypeSwitcher } from '../PrototypeSwitcher';
import { type Cards, type PState, type Resume, ThreadsPrototype } from './ThreadsPrototype';

/**
 * PROTOTYPE (issue #39) — THROWAWAY, lives on branch prototype/stored-threads only.
 *
 * "Three variants of where stored threads live on Ask Naren, switchable via ?variant=, on a
 * throwaway /prototype/threads route." Not on /ask-naren itself because that page is sign-in
 * gated and fetches; this one is mock data, ungated, and sends nothing.
 */
const VARIANTS = [
  { key: 'A', name: 'Left rail on the page' },
  { key: 'B', name: 'Separate threads page' },
  { key: 'C', name: 'Recent-threads dropdown' },
];

const pick = <T extends string>(v: string | string[] | undefined, options: readonly T[]): T =>
  (options as readonly string[]).includes(String(v)) ? (v as T) : options[0];

export default function ThreadsPrototypePage({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const variant = pick(searchParams.variant, ['A', 'B', 'C'] as const);
  const cards = pick<Cards>(searchParams.cards, ['full', 'reduced']);
  const state = pick<PState>(searchParams.state, ['threads', 'empty', 'signed-out']);
  const resume = pick<Resume>(searchParams.resume, ['continue', 'read-only']);

  return (
    <>
      <ThreadsPrototype key={`${variant}-${state}`} variant={variant} cards={cards} state={state} resume={resume} />
      <Suspense>
        <PrototypeSwitcher
          variants={VARIANTS}
          toggles={[
            { param: 'cards', label: 'old turns', options: ['full', 'reduced'] },
            { param: 'state', label: 'state', options: ['threads', 'empty', 'signed-out'] },
            { param: 'resume', label: 'old thread', options: ['continue', 'read-only'] },
          ]}
        />
      </Suspense>
    </>
  );
}
