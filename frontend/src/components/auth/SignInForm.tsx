'use client';

import { useFormState, useFormStatus } from 'react-dom';

import { type SignInState, signIn } from '@/app/login/actions';

const initial: SignInState = { error: null };

const FIELD =
  'w-full rounded-md border border-line bg-surface px-4 py-2.5 text-sm text-ink placeholder:text-ink-placeholder transition-colors duration-fast ease-out-quart focus:border-primary focus:outline-none';

const LABEL = 'text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder';

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="inline-flex h-9 items-center justify-center rounded-sm border border-primary bg-transparent px-4 text-[11px] font-bold uppercase tracking-[0.03em] text-primary transition-colors duration-fast ease-out-quart hover:bg-primary hover:text-white disabled:cursor-not-allowed disabled:border-line disabled:text-ink-placeholder disabled:hover:bg-transparent"
    >
      {pending ? 'Signing in…' : 'Sign in'}
    </button>
  );
}

export function SignInForm({ next }: { next: string }) {
  const [state, action] = useFormState(signIn, initial);
  return (
    <form action={action} className="flex flex-col gap-4">
      <input type="hidden" name="next" value={next} />
      <div className="flex flex-col gap-1.5">
        <label htmlFor="email" className={LABEL}>Email</label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          required
          autoFocus
          placeholder="you@joveo.com"
          className={FIELD}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor="password" className={LABEL}>Password</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          className={FIELD}
        />
      </div>
      {state.error && (
        <p role="alert" className="text-[13px] leading-relaxed text-ink-2">
          {state.error}
        </p>
      )}
      <Submit />
    </form>
  );
}
