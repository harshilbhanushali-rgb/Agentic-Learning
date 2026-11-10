import { redirect } from 'next/navigation';

import { GoogleSignInButton } from '@/components/auth/GoogleSignInButton';
import { SignInForm } from '@/components/auth/SignInForm';
import { safeNext } from '@/server/auth/cookie';
import { getCurrentUser } from '@/server/auth/current-user';
import { type GoogleSignInError, googleConfig } from '@/server/auth/google';

/**
 * What a Google sign-in that came back here means, in fixed copy. Looked up by code, so the
 * page never shows text taken from its own URL -- a link to /login could say anything.
 */
const GOOGLE_ERRORS: Record<GoogleSignInError, string> = {
  google_not_set_up:
    "Your Google account isn't set up for Ask Naren yet. Ask the Ask Naren admin to add you.",
  google_wrong_account:
    'Ask Naren only accepts your verified @joveo.com Google account. Choose that one and try again.',
  google_failed: "Google sign-in didn't finish. Try again.",
  google_off: "Google sign-in isn't available here yet. Use your email and password.",
  unavailable:
    'Sign-in is unavailable right now. This is a fault on our side, not your account — try ' +
    'again in a moment.',
};

function googleError(raw: unknown): string | null {
  return typeof raw === 'string' && Object.hasOwn(GOOGLE_ERRORS, raw)
    ? GOOGLE_ERRORS[raw as GoogleSignInError]
    : null;
}

/**
 * Sign in (issue #44). Users are seeded by an admin; there is no sign-up and no self-service
 * reset, so the page says who to ask instead of offering a link that does not exist. Google
 * is offered first when it is configured (ADR 0017); the password form stays beneath it.
 */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: { next?: string | string[]; error?: string | string[] };
}) {
  const next = safeNext(searchParams.next);
  // Already signed in: a bookmark to /login should not strand someone on a form.
  if (await getCurrentUser()) redirect(next);

  const google = googleConfig() !== null;
  const error = googleError(searchParams.error);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-var(--topbar-height))] max-w-[400px] flex-col justify-center gap-8 px-8 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-[-0.01em] text-ink">Sign in</h1>
        <p className="text-sm leading-relaxed text-ink-2">
          Ask Naren keeps your threads under your Joveo email.
        </p>
      </header>
      {error && (
        <p role="alert" className="text-[13px] leading-relaxed text-ink-2">
          {error}
        </p>
      )}
      {google && (
        <>
          <GoogleSignInButton next={next} />
          <div className="flex items-center gap-3 text-[11px] uppercase tracking-[0.06em] text-ink-placeholder">
            <span className="h-px flex-1 bg-line" />
            or with a password
            <span className="h-px flex-1 bg-line" />
          </div>
        </>
      )}
      <SignInForm next={next} />
      <p className="text-[11px] leading-relaxed text-ink-placeholder">
        Not set up yet, or forgot your password? Ask the Ask Naren admin — passwords are set
        by them, not reset by email.
      </p>
    </div>
  );
}
