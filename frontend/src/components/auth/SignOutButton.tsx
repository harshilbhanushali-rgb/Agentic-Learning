'use client';

import { signOut } from '@/app/login/actions';
import { clearStash } from '@/components/ask-naren/draftStash';
import { clearLegacyThreads } from '@/lib/thread';

/**
 * Sign out of this browser (ADR 0011); the session row goes on the server. Threads live on
 * the server since #46, so there is no conversation in the browser to clear -- only what an
 * older deploy may have left in `localStorage`, and any unsent draft waiting on a sign-in,
 * so nothing of either stays behind on a shared machine.
 */
export function SignOutButton() {
  return (
    <form action={signOut}>
      <button
        type="submit"
        onClick={() => {
          clearLegacyThreads();
          clearStash();
        }}
        className="underline-offset-2 transition-colors duration-fast ease-out-quart hover:text-primary hover:underline"
      >
        Sign out
      </button>
    </form>
  );
}
