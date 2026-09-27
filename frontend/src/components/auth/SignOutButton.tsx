'use client';

import { signOut } from '@/app/login/actions';
import { clearAll } from '@/lib/thread';

/**
 * Sign out of this browser (ADR 0011). Clears the locally held threads first, so nothing of
 * the conversation stays behind on a shared machine; the session row goes on the server.
 */
export function SignOutButton() {
  return (
    <form action={signOut}>
      <button
        type="submit"
        onClick={() => clearAll()}
        className="underline-offset-2 transition-colors duration-fast ease-out-quart hover:text-primary hover:underline"
      >
        Sign out
      </button>
    </form>
  );
}
