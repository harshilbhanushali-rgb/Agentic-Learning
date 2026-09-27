'use client';

import { useMode } from '@/hooks/useMode';
import { WorkspaceGreeting } from '@/components/workspace/WorkspaceGreeting';
import { NewbieGreeting } from '@/components/workspace/NewbieGreeting';
import { EgoTrapCard } from '@/components/workspace/EgoTrapCard';
import { NewbieTrackHero } from '@/components/workspace/NewbieTrackHero';
import { WeeklyRadarCard } from '@/components/workspace/WeeklyRadarCard';
import { NewbieRadarCard } from '@/components/workspace/NewbieRadarCard';
import { TestQueuePanel } from '@/components/workspace/TestQueuePanel';
import { NewbieTestQueuePanel } from '@/components/workspace/NewbieTestQueuePanel';
import { KnowledgeDropsPanel } from '@/components/workspace/KnowledgeDropsPanel';
import { BloomCard } from '@/components/workspace/BloomCard';

export default function WorkspacePage() {
  const mode = useMode();

  return (
    <div className="grid grid-cols-[1fr_var(--right-panel-width)] items-start min-h-[calc(100vh-var(--topbar-height))]">
      <div className="p-8 flex flex-col gap-6 min-w-0 border-r border-line-subtle">
        {mode === 'newbie' ? <NewbieGreeting /> : <WorkspaceGreeting />}
        {mode === 'newbie' ? <NewbieTrackHero /> : <EgoTrapCard />}
        {mode === 'newbie' ? <NewbieRadarCard /> : <WeeklyRadarCard />}
      </div>
      <aside className="px-5 py-6 flex flex-col gap-6 sticky top-[var(--topbar-height)] max-h-[calc(100vh-var(--topbar-height))] overflow-y-auto">
        {mode === 'newbie' ? <NewbieTestQueuePanel /> : <TestQueuePanel />}
        {mode === 'newbie' ? <BloomCard /> : <KnowledgeDropsPanel />}
      </aside>
    </div>
  );
}
