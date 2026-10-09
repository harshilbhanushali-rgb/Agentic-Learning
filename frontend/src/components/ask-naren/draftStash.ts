/**
 * Where an unsent question -- and the thread it was going into -- waits while its author
 * signs back in (ADR 0011: "on expiry mid-thread the CSM signs in and returns to the same
 * thread with the unsent draft kept").
 *
 * sessionStorage rather than localStorage: it belongs to this tab's trip through /login and
 * nothing longer. Tagged with the user, so a different person signing in on this browser
 * inherits neither the draft nor the thread (and could not open the thread anyway -- the
 * thread APIs are owner-scoped -- but should not even be sent looking for it).
 *
 * A NORMAL SIGN-IN FINDS NO STASH and lands on an empty box (#39). Only a sign-in that this
 * page itself sent someone to reopens anything.
 */

const DRAFT_KEY = 'cs-ask-naren-draft';

export interface Stash {
  draft: string;
  threadId: number | null;
}

/** Keep the draft and thread, then go and sign in; `/login` sends them back here. */
export function stashAndSignIn(userId: number, stash: Stash): void {
  try {
    window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ userId, ...stash }));
  } catch {
    // Storage unavailable: the draft is lost, the sign-in still happens.
  }
  window.location.assign(`/login?next=${encodeURIComponent('/ask-naren')}`);
}

/** The stash for this user, once -- reading it removes it. */
export function takeStash(userId: number): Stash | null {
  try {
    const raw = window.sessionStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(DRAFT_KEY);
    const s = JSON.parse(raw) as { userId?: unknown; draft?: unknown; threadId?: unknown };
    if (s.userId !== userId) return null;
    return {
      draft: typeof s.draft === 'string' ? s.draft : '',
      threadId:
        typeof s.threadId === 'number' && Number.isSafeInteger(s.threadId) && s.threadId > 0
          ? s.threadId
          : null,
    };
  } catch {
    return null;
  }
}

/** Signing out on purpose leaves no draft behind. */
export function clearStash(): void {
  try {
    window.sessionStorage.removeItem(DRAFT_KEY);
  } catch {
    // Storage unavailable: there is nothing in it to clear.
  }
}
