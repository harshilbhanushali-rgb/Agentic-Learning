import type { Db } from '../db';
import type { Role } from './sessions';
import {
  UserError,
  addUser,
  disableUser,
  enableUser,
  listUsers,
  normalizeEmail,
  setRole,
  signOutEverywhere,
} from './users';

/**
 * The admin's command-line tool -- the way back in if /admin is ever unreachable (ADR 0016,
 * 0018). scripts/users.ts is the thin shell around this; the logic lives here so it is tested.
 * People sign in with Google, so there are no passwords to set or hand over.
 */
export const USAGE = `Usage: npm run users -- <command>

  add <email> <name>              Add a member. They sign in with their Joveo Google account.
  role <email> <member|admin>     Set what they may do. Admins also manage users on /admin.
  disable <email>                 Offboard: block sign-in and sign out everywhere.
  enable <email>                  Undo disable.
  sign-out <email>                Sign the user out on every browser.
  list                            Every user, with role, status and session count.

Uses ASK_NAREN_ADMIN_DATABASE_URL if set, else ASK_NAREN_DATABASE_URL (environment or .env.local).`;

export interface CliIo {
  out: (line: string) => void;
}

/** Returns the process exit code. */
export async function runCli(argv: string[], db: Db, io: CliIo): Promise<number> {
  const [command, ...args] = argv;
  try {
    switch (command) {
      case 'add': {
        const [email, ...nameParts] = args;
        if (!email || !nameParts.length) break;
        await addUser(db, { email, name: nameParts.join(' ') });
        io.out(`Added ${normalizeEmail(email)}. They sign in with Google.`);
        return 0;
      }
      case 'role': {
        const [email, role] = args;
        if (!email || !role) break;
        await setRole(db, email, role as Role);
        io.out(`${normalizeEmail(email)} is now ${role === 'admin' ? 'an admin' : 'a member'}.`);
        return 0;
      }
      case 'disable': {
        const [email] = args;
        if (!email) break;
        const ended = await disableUser(db, email);
        io.out(`Disabled; ${ended} session(s) ended.`);
        return 0;
      }
      case 'enable': {
        const [email] = args;
        if (!email) break;
        await enableUser(db, email);
        io.out('Enabled.');
        return 0;
      }
      case 'sign-out': {
        const [email] = args;
        if (!email) break;
        const ended = await signOutEverywhere(db, email);
        io.out(`${ended} session(s) ended.`);
        return 0;
      }
      case 'list': {
        const users = await listUsers(db);
        if (!users.length) io.out('No users.');
        for (const u of users) {
          const status = u.disabledAt ? 'disabled' : u.googleLinked ? 'active' : 'not signed in yet';
          io.out(`${u.email}\t${u.name}\t${u.role}\t${status}\t${u.sessions} session(s)`);
        }
        return 0;
      }
    }
    io.out(USAGE);
    return 2;
  } catch (err) {
    if (err instanceof UserError) {
      io.out(`Error: ${err.message}`);
      return 1;
    }
    throw err;
  }
}
