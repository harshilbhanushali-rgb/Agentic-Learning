'use client';

import { useEffect, useId, useRef } from 'react';
import { useFormState, useFormStatus } from 'react-dom';

import { addUserAction, setDisabledAction, setRoleAction } from '@/app/admin/actions';
import { EMPTY_RESULT, type AdminResult } from '@/server/auth/admin-web-result';

import { AdminTabs } from './AdminTabs';

export interface AdminUserRow {
  email: string;
  name: string;
  role: 'member' | 'admin';
  /** The built-in admin: always an admin, never changed or disabled from this page. */
  fixedAdmin: boolean;
  /** Has signed in with Google at least once. */
  googleLinked: boolean;
  disabled: boolean;
  sessions: number;
}

const FIELD =
  'w-full rounded-md border border-line bg-bg px-3.5 py-2.5 text-[14px] text-ink placeholder:text-ink-placeholder transition-colors duration-fast ease-out-quart focus:border-primary focus:outline-none';
const LABEL = 'text-[13px] font-semibold text-ink';
const PRIMARY =
  'inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-[14px] font-semibold text-white transition-colors duration-fast ease-out-quart hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60';
const SECONDARY =
  'inline-flex h-9 items-center justify-center rounded-md border border-line bg-bg px-3 text-[13px] font-semibold text-ink transition-colors duration-fast ease-out-quart hover:bg-surface-raised disabled:cursor-not-allowed disabled:opacity-60';

function Submit({ children, pendingText, className = PRIMARY }: { children: string; pendingText: string; className?: string }) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" disabled={pending} className={className}>
      {pending ? pendingText : children}
    </button>
  );
}

/** What an action said. */
function Outcome({ result }: { result: AdminResult }) {
  if (!result.ok && !result.error) return null;
  return (
    <div role="status" className="flex flex-col gap-2">
      {result.error && <p className="text-[14px] font-medium text-error">{result.error}</p>}
      {result.ok && <p className="text-[14px] text-ink">{result.ok}</p>}
    </div>
  );
}

function AddUserForm() {
  const [state, action] = useFormState(addUserAction, EMPTY_RESULT);
  const form = useRef<HTMLFormElement>(null);
  const ids = { email: useId(), name: useId() };

  // Clear the fields once the user exists, so a second click cannot add them twice.
  useEffect(() => { if (state.ok) form.current?.reset(); }, [state]);

  return (
    <section aria-labelledby="add-user" className="flex flex-col gap-4 rounded-xl border border-line bg-bg p-6">
      <h2 id="add-user" className="text-[17px] font-semibold text-ink">Add a user</h2>
      <form ref={form} action={action} className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <label htmlFor={ids.email} className={LABEL}>Email</label>
          <input id={ids.email} name="email" type="email" required autoComplete="off" placeholder="name@joveo.com" className={FIELD} />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={ids.name} className={LABEL}>Name</label>
          <input id={ids.name} name="name" required autoComplete="off" placeholder="Full name" className={FIELD} />
        </div>
        <div className="md:col-span-2">
          <Submit pendingText="Adding…">Add user</Submit>
        </div>
      </form>
      <Outcome result={state} />
    </section>
  );
}

/** Member or admin. Changing it saves at once; locked for yourself and the built-in admin. */
function RoleSelect({ user, locked, action }: { user: AdminUserRow; locked: boolean; action: (form: FormData) => void }) {
  const form = useRef<HTMLFormElement>(null);
  const id = useId();
  const role = user.fixedAdmin ? 'admin' : user.role;
  return (
    <form ref={form} action={action}>
      <input type="hidden" name="email" value={user.email} />
      <label htmlFor={id} className="sr-only">Role for {user.email}</label>
      <select
        id={id}
        name="role"
        defaultValue={role}
        disabled={locked}
        title={user.fixedAdmin ? 'Always an admin' : locked ? 'You can’t change your own role' : undefined}
        onChange={() => form.current?.requestSubmit()}
        className="h-9 rounded-md border border-line bg-bg px-2.5 text-[13px] font-semibold text-ink transition-colors duration-fast ease-out-quart focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
      >
        <option value="member">Member</option>
        <option value="admin">Admin</option>
      </select>
    </form>
  );
}

function UserRow({ user, isMe }: { user: AdminUserRow; isMe: boolean }) {
  const [roleState, roleAction] = useFormState(setRoleAction, EMPTY_RESULT);
  const [statusState, statusAction] = useFormState(setDisabledAction, EMPTY_RESULT);
  const locked = isMe || user.fixedAdmin;

  const status = user.disabled ? 'Disabled' : user.googleLinked ? 'Active' : 'Not signed in yet';
  const latest = statusState.ok || statusState.error ? statusState : roleState;

  return (
    <tbody className="border-t border-line">
      <tr className="align-top">
        <td className="px-4 py-3 text-[14px] font-medium text-ink">
          {user.name}
          {isMe && <span className="ml-2 text-[12px] font-normal text-ink-2">(you)</span>}
        </td>
        <td className="break-all px-4 py-3 text-[14px] text-ink">{user.email}</td>
        <td className="px-4 py-3">
          <RoleSelect user={user} locked={locked} action={roleAction} />
        </td>
        <td className="px-4 py-3 text-[14px]">
          <span className={user.disabled ? 'font-semibold text-error' : user.googleLinked ? 'text-ink' : 'text-ink-2'}>
            {status}
          </span>
        </td>
        <td className="px-4 py-3 text-[14px] text-ink">
          {user.sessions === 1 ? '1 browser' : `${user.sessions} browsers`}
        </td>
        <td className="px-4 py-3">
          <form action={statusAction}>
            <input type="hidden" name="email" value={user.email} />
            <input type="hidden" name="disable" value={user.disabled ? 'false' : 'true'} />
            {locked && !user.disabled ? (
              <button
                type="button"
                disabled
                title={user.fixedAdmin ? 'Always an admin' : 'You can’t disable your own account'}
                className={SECONDARY}
              >
                Disable
              </button>
            ) : (
              <Submit pendingText={user.disabled ? 'Enabling…' : 'Disabling…'} className={SECONDARY}>
                {user.disabled ? 'Enable' : 'Disable'}
              </Submit>
            )}
          </form>
        </td>
      </tr>
      {(latest.ok || latest.error) && (
        <tr>
          <td colSpan={6} className="px-4 pb-4">
            <Outcome result={latest} />
          </td>
        </tr>
      )}
    </tbody>
  );
}

export function AdminPanel({ me, users }: { me: string; users: AdminUserRow[] | null }) {
  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-8 px-6 py-10">
      <AdminTabs current="people" />
      <header className="flex flex-col gap-2">
        <h1 className="text-[28px] font-bold tracking-[-0.02em] text-ink">Users</h1>
        <p className="max-w-[70ch] text-[15px] leading-relaxed text-ink-2">
          Anyone with a Joveo Google account can sign in, and joins as a member the first time.
          Here you choose who is an admin, turn sign-in off or on, and can add people ahead of
          time. Only admins can see this page.
        </p>
      </header>

      <AddUserForm />

      <section aria-labelledby="all-users" className="flex flex-col gap-3">
        <h2 id="all-users" className="text-[17px] font-semibold text-ink">
          Everyone who can sign in{users ? ` (${users.length})` : ''}
        </h2>
        {users === null ? (
          <p role="alert" className="text-[14px] text-error">
            Could not load the user list just now. This is a fault on our side — try again in a
            moment.
          </p>
        ) : users.length === 0 ? (
          <p className="text-[14px] text-ink-2">No users yet. Add the first one above.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-line bg-bg">
            <table className="w-full min-w-[760px] border-collapse text-left">
              <thead className="bg-surface">
                <tr>
                  {['Name', 'Email', 'Role', 'Status', 'Signed in on', 'Actions'].map(h => (
                    <th key={h} scope="col" className="px-4 py-2.5 text-[13px] font-semibold text-ink-2">{h}</th>
                  ))}
                </tr>
              </thead>
              {users.map(u => (
                <UserRow key={u.email} user={u} isMe={u.email === me.toLowerCase()} />
              ))}
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
