import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { WorkspaceGreeting } from './WorkspaceGreeting';
import { NewbieGreeting } from './NewbieGreeting';
import { KnowledgeDropsPanel } from './KnowledgeDropsPanel';
import { TestQueuePanel } from './TestQueuePanel';
import { NewbieTestQueuePanel } from './NewbieTestQueuePanel';
import { BloomCard } from './BloomCard';
import { NewbieRadarCard } from './NewbieRadarCard';
import { NewbieTrackHero } from './NewbieTrackHero';
import { WeeklyRadarCard } from './WeeklyRadarCard';
import { KNOWLEDGE_DROPS, TEST_QUEUE, NEWBIE_TEST_QUEUE, BLOOM_STAGES, NEWBIE_TRACK, RADAR_MEETINGS } from '@/data/workspace';

/* These panels take no props -- they read src/data directly -- so a render is the whole
 * surface. Each assertion is tied back to the data module rather than to a copied string,
 * so editing the fixture data does not silently turn these into assertions about nothing. */

describe('workspace greetings', () => {
  it('veteran greeting leads with the day’s meetings', () => {
    render(<WorkspaceGreeting />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/two meetings on the deck/i);
  });

  it('newbie greeting leads with track progress', () => {
    render(<NewbieGreeting />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/days into your track/i);
  });
});

describe('side panels', () => {
  it('knowledge drops lists every drop and counts them', () => {
    render(<KnowledgeDropsPanel />);
    expect(screen.getByText(`${KNOWLEDGE_DROPS.length} new`)).toBeInTheDocument();
    for (const drop of KNOWLEDGE_DROPS) {
      expect(screen.getByText(drop.title)).toBeInTheDocument();
    }
  });

  it('veteran test queue names the tier of the active item', () => {
    render(<TestQueuePanel />);
    const activeTier = TEST_QUEUE.find(i => i.status === 'active')?.tier ?? 1;
    expect(screen.getByText(`Waterfall · Tier ${activeTier} of 3`)).toBeInTheDocument();
    expect(screen.getAllByText(TEST_QUEUE[0].title)[0]).toBeInTheDocument();
  });

  it('newbie test queue is fixed rather than tiered', () => {
    render(<NewbieTestQueuePanel />);
    expect(screen.getByText(/Fixed · mandatory until day 90/)).toBeInTheDocument();
    expect(screen.getAllByText(NEWBIE_TEST_QUEUE[0].title)[0]).toBeInTheDocument();
  });

  it('bloom card renders every stage', () => {
    render(<BloomCard />);
    for (const stage of BLOOM_STAGES) {
      expect(screen.getByText(stage.label)).toBeInTheDocument();
    }
  });
});

describe('radar cards', () => {
  it('newbie radar renders each meeting plus the static cohort sync', () => {
    render(<NewbieRadarCard />);
    expect(screen.getByText('Cohort sync')).toBeInTheDocument();
    expect(screen.getByText(/Aryan is the lead/)).toBeInTheDocument();
  });

  it('weekly radar summarises the meeting count', () => {
    render(<WeeklyRadarCard />);
    expect(
      screen.getByText(new RegExp(`${RADAR_MEETINGS.length} meetings`)),
    ).toBeInTheDocument();
  });
});

describe('NewbieTrackHero', () => {
  it('states the phase and progress from the track data', () => {
    render(<NewbieTrackHero />);
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(
      `Phase ${NEWBIE_TRACK.phase} · ${NEWBIE_TRACK.phaseLabel} — ${NEWBIE_TRACK.progress}% complete`,
    );
  });

  it('reveals the next-up list on demand and hides it again', async () => {
    const user = userEvent.setup();
    render(<NewbieTrackHero />);

    await user.click(screen.getByRole('button', { name: /What's next/ }));
    expect(screen.getByRole('button', { name: /Hide/ })).toBeInTheDocument();
    expect(screen.getByText(NEWBIE_TRACK.nextUp[0].desc)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Hide/ }));
    expect(screen.getByRole('button', { name: /What's next/ })).toBeInTheDocument();
  });
});
