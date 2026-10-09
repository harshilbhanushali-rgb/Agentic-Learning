import { redirect } from 'next/navigation';

import { SignInForm } from '@/components/auth/SignInForm';
import { safeNext } from '@/server/auth/cookie';
import { getCurrentUser } from '@/server/auth/current-user';

/**
 * Sign in (issue #44). Users are seeded by an admin; there is no sign-up and no self-service
 * reset, so the page says who to ask instead of offering a link that does not exist.
 */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: { next?: string | string[] };
}) {
  const next = safeNext(searchParams.next);
  // Already signed in: a bookmark to /login should not strand someone on a form.
  if (await getCurrentUser()) redirect(next);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-var(--topbar-height))] max-w-[400px] flex-col justify-center gap-8 px-8 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-[-0.01em] text-ink">Sign in</h1>
        <p className="text-sm leading-relaxed text-ink-2">
          Ask Naren keeps your threads under your Joveo email.
        </p>
      </header>
      <SignInForm next={next} />
      <p className="text-[11px] leading-relaxed text-ink-placeholder">
        Not set up yet, or forgot your password? Ask the Ask Naren admin — passwords are set
        by them, not reset by email.
      </p>
    </div>
  );
}
