'use client';

import { useState } from 'react';
import type { KeyboardEvent } from 'react';
import { RadarBriefingPanel } from '@/components/shared/RadarBriefingPanel';
import { ChevronLeftIcon, ChevronRightIcon, ChevronUpIcon } from '@/components/icons';
import type { RadarMeeting, PrepStatus } from '@/types';

function RadarDeckNav({ activeIndex, total, onPrev, onNext }: {
  activeIndex: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="radar-deck-nav">
      <button
        className="rdn-arrow rdn-arrow--prev"
        onClick={onPrev}
        disabled={activeIndex === 0}
        aria-label="Previous meeting"
      >
        <ChevronLeftIcon />
      </button>
      <span className="rdn-counter">
        {activeIndex + 1} / {total}
      </span>
      <button
        className="rdn-arrow rdn-arrow--next"
        onClick={onNext}
        disabled={activeIndex === total - 1}
        aria-label="Next meeting"
      >
        <ChevronRightIcon />
      </button>
    </div>
  );
}

function RadarDeckCard({ meeting, slot, open, onToggle }: {
  meeting: RadarMeeting | null;
  slot: string;
  open: boolean;
  onToggle: (() => void) | null;
}) {
  const isFront = slot === 'front';

  const chipClass = meeting ? (({
    'ready':       'radar-prep--ready',
    'in-progress': 'radar-prep--progress',
    'cold':        'radar-prep--cold',
  } as Record<PrepStatus, string>)[meeting.prepStatus] || 'radar-prep--progress') : '';

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onToggle?.();
    }
  };

  if (!meeting) {
    return (
      <div
        className="radar-deck-card"
        data-slot={slot}
        aria-hidden="true"
        tabIndex={-1}
      />
    );
  }

  return (
    <div
      className={`radar-deck-card${open ? ' is-open' : ''}`}
      data-slot={slot}
      aria-hidden={!isFront ? 'true' : undefined}
      tabIndex={isFront ? undefined : -1}
    >
      <div
        className="rdc-clickable"
        onClick={isFront && onToggle ? onToggle : undefined}
        onKeyDown={isFront ? handleKeyDown : undefined}
        role={isFront ? 'button' : undefined}
        aria-expanded={isFront ? open : undefined}
        tabIndex={isFront ? 0 : -1}
      >
        <div className="rdc-header">
          <div className="rdc-time-row">
            <span className="rdc-day">{meeting.day}</span>
            <span className="rdc-dot" aria-hidden="true">·</span>
            <span className="rdc-time">{meeting.time}</span>
            <span className="rdc-dot" aria-hidden="true">·</span>
            <span className="rdc-relative">{meeting.relative}</span>
          </div>
          <span className={`radar-prep ${chipClass}`}>{meeting.prepLabel}</span>
        </div>

        <div className="rdc-title-row">
          <span className="rdc-account">{meeting.account}</span>
          <span className="rdc-sep" aria-hidden="true"> · </span>
          <span className="rdc-meeting-name">{meeting.title}</span>
        </div>

        <div className="rdc-meta-row">{meeting.industry} · {meeting.tags}</div>
      </div>

      {isFront && (
        <div className="rdc-expand">
          <div className="rdc-expand-inner">
            <div className="rdc-briefing-wrap">
              <RadarBriefingPanel meeting={meeting} />
            </div>
            <div className="rdc-expand-footer">
              <button
                className="rdc-close-btn"
                onClick={onToggle ?? undefined}
                aria-label="Hide briefing"
              >
                Hide briefing <ChevronUpIcon />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function RadarDeckStack({ meetings }: { meetings: RadarMeeting[] }) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [open, setOpen] = useState(false);
  const [navigating, setNavigating] = useState(false);

  const navigate = (newIndex: number) => {
    if (navigating) return;
    const reduceMotion = typeof window !== 'undefined'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (open && !reduceMotion) {
      // Let the briefing collapse before swapping the front card.
      setNavigating(true);
      setOpen(false);
      setTimeout(() => {
        setActiveIndex(newIndex);
        setNavigating(false);
      }, 360);
    } else {
      setOpen(false);
      setActiveIndex(newIndex);
    }
  };

  const frontMeeting = meetings[activeIndex];
  const midMeeting   = meetings[activeIndex + 1] ?? null;
  const backMeeting  = meetings[activeIndex + 2] ?? null;

  return (
    <div className={`deck-is-open-wrapper${open ? ' deck-is-open' : ''}`}>
      <div className="radar-deck-wrap">
        <RadarDeckCard meeting={backMeeting} slot="back" open={false} onToggle={null} />
        <RadarDeckCard meeting={midMeeting}  slot="mid"  open={false} onToggle={null} />
        <RadarDeckCard meeting={frontMeeting} slot="front" open={open} onToggle={() => setOpen(o => !o)} />
      </div>
      <RadarDeckNav
        activeIndex={activeIndex}
        total={meetings.length}
        onPrev={() => navigate(activeIndex - 1)}
        onNext={() => navigate(activeIndex + 1)}
      />
      {/* Announce the front meeting to screen readers when paging through the deck. */}
      <span className="sr-only" role="status" aria-live="polite">
        {frontMeeting
          ? `Showing ${frontMeeting.account}, ${frontMeeting.title}. Meeting ${activeIndex + 1} of ${meetings.length}. Prep: ${frontMeeting.prepLabel}.`
          : ''}
      </span>
    </div>
  );
}
