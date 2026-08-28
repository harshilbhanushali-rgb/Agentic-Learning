'use client';

import { useState } from 'react';
import type { Citation } from '@/types';
import { ChevronDownIcon, ChevronRightIcon } from '@/components/icons';

/* Grounding is the product's credibility mechanic, so citations are
 * first-class objects from the wire — never substrings parsed out of
 * the answer text. */

const KIND_LABEL: Record<Citation['kind'], string> = {
  module:       'MODULE',
  'case-study': 'CASE STUDY',
  failure:      'FAILURE',
  transcript:   'TRANSCRIPT',
  account:      'ACCOUNT',
};

const KIND_CLASS: Record<Citation['kind'], string> = {
  module:       'text-primary bg-primary-surface',
  'case-study': 'text-accent-ink bg-accent-surface',
  failure:      'text-error bg-error-surface',
  transcript:   'text-ink-2 bg-surface-raised',
  account:      'text-success bg-success-surface',
};

export function CitationChip({ citation, index }: { citation: Citation; index: number }) {
  const [open, setOpen] = useState(false);
  const expandable = Boolean(citation.excerpt);

  return (
    <li className="rounded-md border border-line-subtle bg-surface overflow-hidden">
      <button
        type="button"
        onClick={() => expandable && setOpen(o => !o)}
        aria-expanded={expandable ? open : undefined}
        disabled={!expandable}
        className={`w-full flex items-center gap-2 px-3 py-2 text-left transition-colors duration-fast
          ${expandable ? 'hover:bg-surface-raised cursor-pointer' : 'cursor-default'}`}
      >
        <span className="text-[10px] font-semibold tabular-nums text-ink-placeholder w-4 shrink-0">
          {index + 1}
        </span>
        <span className={`text-[9px] font-semibold tracking-[0.06em] px-1.5 py-0.5 rounded-sm shrink-0
          ${KIND_CLASS[citation.kind]}`}>
          {KIND_LABEL[citation.kind]}
        </span>
        <span className="text-xs text-ink truncate flex-1">{citation.label}</span>
        {expandable && (
          <span className="text-ink-placeholder shrink-0" aria-hidden="true">
            {open ? <ChevronDownIcon /> : <ChevronRightIcon />}
          </span>
        )}
      </button>

      {open && citation.excerpt && (
        <p className="px-3 pb-3 pl-9 text-xs text-ink-2 leading-base border-t border-line-subtle pt-2">
          &ldquo;{citation.excerpt}&rdquo;
        </p>
      )}
    </li>
  );
}
