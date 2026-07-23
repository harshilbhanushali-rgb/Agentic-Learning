'use client';
import type { CaseStudy } from '@/types';

import { useState } from 'react';
import { CASE_STUDIES } from '@/data/library';
import { CaseStudyCard } from '@/components/library/CaseStudyCard';
import { CaseStudyModal } from '@/components/library/CaseStudyModal';

export function CaseStudiesTab() {
  const [open, setOpen] = useState<CaseStudy | null>(null);
  return (
    <div>
      <p className="text-sm text-ink-2 leading-base mb-6 max-w-[62ch]">
        Accounts told in chapters as they evolve — both new and existing. Open one to read the full arc.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {CASE_STUDIES.map(cs => (
          <CaseStudyCard key={cs.id} cs={cs} onOpen={setOpen} />
        ))}
      </div>
      {open && <CaseStudyModal cs={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
