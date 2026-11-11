import { redirect } from 'next/navigation';

import { GoogleSignInButton } from '@/components/auth/GoogleSignInButton';
import { safeNext } from '@/server/auth/cookie';
import { getCurrentUser } from '@/server/auth/current-user';
import { type GoogleSignInError, googleConfig } from '@/server/auth/google';

/**
 * What a Google sign-in that came back here means, in fixed copy. Looked up by code, so the
 * page never shows text taken from its own URL -- a link to /login could say anything.
 */
const GOOGLE_ERRORS: Record<GoogleSignInError, string> = {
  google_refused:
    "Your access to Ask Naren is turned off. Ask the Ask Naren admin if that's a mistake.",
  google_wrong_account:
    'Ask Naren only accepts your verified @joveo.com Google account. Choose that one and try again.',
  google_failed: "Google sign-in didn't finish. Try again.",
  google_off: "Google sign-in isn't available on this site right now.",
  unavailable:
    'Sign-in is unavailable right now. This is a fault on our side, not your account — try ' +
    'again in a moment.',
};

/** Shown when the site has no Google client configured: there is then no way in at all. */
const NOT_CONFIGURED =
  "Sign-in isn't set up on this site yet. This is a fault on our side — tell the Ask Naren admin.";

function googleError(raw: unknown): string | null {
  return typeof raw === 'string' && Object.hasOwn(GOOGLE_ERRORS, raw)
    ? GOOGLE_ERRORS[raw as GoogleSignInError]
    : null;
}

/**
 * Sign in (issue #44, ADR 0018, ADR 0019): with a Joveo Google account, and nothing else. Any
 * Joveo account may sign in; the first time, it joins as a member.
 */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: { next?: string | string[]; error?: string | string[] };
}) {
  const next = safeNext(searchParams.next);
  // Already signed in: a bookmark to /login should not strand someone here.
  if (await getCurrentUser()) redirect(next);

  const google = googleConfig() !== null;
  const error = google ? googleError(searchParams.error) : NOT_CONFIGURED;

  return (
    <div className="mx-auto flex min-h-[calc(100vh-var(--topbar-height))] max-w-[400px] flex-col justify-center gap-8 px-8 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-[-0.01em] text-ink">Sign in</h1>
        <p className="text-sm leading-relaxed text-ink-2">
          Use your Joveo Google account. Ask Naren keeps your threads under it.
        </p>
      </header>
      {error && (
        <p role="alert" className="text-[13px] leading-relaxed text-ink-2">
          {error}
        </p>
      )}
      {google && <GoogleSignInButton next={next} />}
      <p className="text-[11px] leading-relaxed text-ink-placeholder">
        Anyone with a Joveo Google account can sign in.
      </p>
    </div>
  );
}
