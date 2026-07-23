'use client';

import { KNOWLEDGE_DROPS } from '@/data/workspace';
import { ChevronRightIcon } from '@/components/icons';

export function KnowledgeDropsPanel() {
  return (
    <div className="flex flex-col gap-3 pt-4 border-t border-line-subtle">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-bold text-ink tracking-[-0.01em]">Knowledge drops</h3>
        <span className="inline-flex items-center h-[18px] px-2 rounded-full bg-primary-surface text-primary text-[10px] font-bold tracking-[0.02em] uppercase shrink-0 mt-0.5">{KNOWLEDGE_DROPS.length} new</span>
      </div>
      <div className="flex flex-col gap-1">
        {KNOWLEDGE_DROPS.map(d => (
          <button key={d.id} className="flex items-center gap-2 px-3 py-2 rounded-sm bg-transparent cursor-pointer text-left w-full transition-colors duration-fast ease-out-quart hover:bg-surface-raised">
            <span className="text-[9px] font-bold text-primary tracking-[0.06em] uppercase whitespace-nowrap shrink-0 bg-primary-subtle px-[5px] py-0.5 rounded-[3px]">{d.type}</span>
            <span className="text-xs font-medium text-ink flex-1 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap leading-snug">{d.title}</span>
            <span className="ml-auto text-ink-placeholder shrink-0"><ChevronRightIcon /></span>
          </button>
        ))}
      </div>
    </div>
  );
}
