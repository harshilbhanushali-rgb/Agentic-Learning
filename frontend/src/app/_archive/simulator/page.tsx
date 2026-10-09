'use client';

import { useState } from 'react';
import { OriginButton } from '@/components/ui/origin-button';

export default function Simulator() {
  const [notified, setNotified] = useState(false);

  return (
    <div className="flex flex-col items-center justify-center min-h-[calc(100vh-var(--topbar-height))] p-12 text-center text-ink-2 gap-4">
      <h1 className="text-2xl font-bold text-ink">The Simulator</h1>
      <p className="text-base max-w-md text-balance">AI roleplay, blind diagnosis, QBR defense. Coming next.</p>
      <div className="mt-4 flex flex-col items-center gap-3">
        <OriginButton
          disabled={notified}
          onClick={() => setNotified(true)}
        >
          {notified ? "You're on the list ✓" : 'Notify me when it launches'}
        </OriginButton>
        <span className="text-xs text-ink-placeholder">
          {notified ? "We'll ping you the moment it's ready." : 'Be first in your cohort to run a session.'}
        </span>
      </div>
    </div>
  );
}
