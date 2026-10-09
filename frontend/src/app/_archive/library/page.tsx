'use client';
import type { FailureEntry } from '@/types';

import { useState } from 'react';
import { useMode } from '@/hooks/useMode';
import { CoursesTab } from '@/components/library/CoursesTab';
import { CaseStudiesTab } from '@/components/library/CaseStudiesTab';
import { FailureLibraryTab } from '@/components/library/FailureLibraryTab';
import { FailureModal } from '@/components/library/FailureModal';

const TABS = [
  { id: 'courses', label: 'Courses' },
  { id: 'case-studies', label: 'Case Studies' },
  { id: 'failure-library', label: 'Failure Library' },
];

export default function Library() {
  const mode = useMode();
  const [activeTab, setActiveTab] = useState('courses');
  const [openModal, setOpenModal] = useState<FailureEntry | null>(null);

  return (
    <div className="p-8 pb-16 w-full">
      <header className="flex items-baseline justify-between mb-5">
        <h1 className="text-2xl font-bold text-ink tracking-[-0.025em]">The Library</h1>
        <span className="text-sm font-medium text-ink-2">
          Filtered for {mode === 'veteran' ? 'Veteran' : 'Newbie'}
        </span>
      </header>

      <nav className="flex border-b border-line-subtle mb-8 sticky top-[var(--topbar-height)] bg-surface z-[199] -mx-8 pl-8" aria-label="Library sections">
        {TABS.map(tab => {
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              className={`bg-none border-b-2 px-4 py-3 text-sm cursor-pointer -mb-px whitespace-nowrap transition duration-fast ease-out-quart ${active ? 'text-ink border-accent font-semibold' : 'text-ink-2 border-transparent font-medium hover:text-ink'}`}
              onClick={() => setActiveTab(tab.id)}
              aria-current={active ? 'page' : undefined}
            >
              {tab.label}
            </button>
          );
        })}
      </nav>

      <div className="anim-content-enter" key={activeTab}>
        {activeTab === 'courses' && <CoursesTab mode={mode} />}
        {activeTab === 'case-studies' && <CaseStudiesTab />}
        {activeTab === 'failure-library' && <FailureLibraryTab onOpen={setOpenModal} />}
      </div>

      {openModal && (
        <FailureModal entry={openModal} onClose={() => setOpenModal(null)} />
      )}
    </div>
  );
}
