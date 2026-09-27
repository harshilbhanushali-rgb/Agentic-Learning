'use client';

import { useRouter } from 'next/navigation';
import { useTransition } from 'react';

/**
 * What /ask-naren shows when it cannot load (#40): in practice the store behind sign-in and
 * threads is unreachable, because the session check and the rail are the page's only reads.
 * ADR 0011 has no stateless fallback, so nobody can be recognised as signed in -- and this
 * must not read as "signed out", which would send a CSM to a sign-in page that cannot work
 * either. Replaces Next's bare "Application error".
 *
 * Retry re-runs the server render (`router.refresh`) as well as resetting the boundary,
 * because the failure happened on the server and `reset` alone would only re-render the
 * client with the same error.
 */
export default function AskNarenError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const router = useRouter();
  const [retrying, startRetry] = useTransition();

  return (
    <div className="mx-auto flex min-h-[calc(100vh-var(--topbar-height))] max-w-[560px] flex-col justify-center gap-6 px-8 py-10">
      <article className="flex flex-col gap-3 rounded-md border border-dashed border-line bg-surface-raised p-6">
        <h1 className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
          Ask Naren can&rsquo;t reach your threads
        </h1>
        <p className="text-sm leading-relaxed text-ink-2">
          Ask Naren could not check your sign-in or load your threads just now. This is a fault
          on our side — you have not been signed out, and nothing you asked before is lost. Try
          again in a moment.
        </p>
        {error.digest && (
          // Something to quote to whoever looks into it; the server log has the same digest.
          <p className="text-[11px] text-ink-placeholder">Reference: {error.digest}</p>
        )}
        <div>
          <button
            type="button"
            disabled={retrying}
            onClick={() => startRetry(() => { router.refresh(); reset(); })}
            className="inline-flex h-9 items-center rounded-sm border border-primary px-4 text-[11px] font-bold uppercase tracking-[0.03em] text-primary transition-colors duration-fast ease-out-quart hover:bg-primary hover:text-white disabled:opacity-60"
          >
            {retrying ? 'Trying…' : 'Try again'}
          </button>
        </div>
      </article>
    </div>
  );
}
