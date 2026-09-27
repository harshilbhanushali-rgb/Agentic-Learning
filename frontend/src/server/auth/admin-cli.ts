import { randomBytes } from 'node:crypto';

import type { Db } from '../db';
import { MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH } from './password';
import {
  UserError,
  addUser,
  disableUser,
  enableUser,
  listUsers,
  setPassword,
  signOutEverywhere,
} from './users';

/**
 * The admin's only tool (ADR 0011: admin-seeded users, no self-service, no admin UI).
 * scripts/users.ts is the thin shell around this; the logic lives here so it is tested.
 *
 * A PASSWORD IS NEVER TAKEN AS A COMMAND-LINE ARGUMENT, because that lands in shell history
 * and process listings. It is generated and printed once, or read from stdin.
 */
export const USAGE = `Usage: npm run users -- <command>

  add <email> <name> [--password-stdin]   Create a user. Prints a generated password once,
                                          unless one is piped on stdin.
  set-password <email> [--password-stdin] Replace a password. Signs the user out everywhere.
  disable <email>                         Offboard: block sign-in and sign out everywhere.
  enable <email>                          Undo disable.
  sign-out <email>                        Sign the user out on every browser.
  list                                    Every user, with status and session count.

Needs ASK_NAREN_ADMIN_DATABASE_URL (read from the environment or .env.local).`;

export interface CliIo {
  out: (line: string) => void;
  readStdin: () => Promise<string>;
}

function generatePassword(): string {
  return randomBytes(18).toString('base64url');
}

async function passwordFrom(flags: string[], io: CliIo): Promise<{ password: string; generated: boolean }> {
  if (!flags.includes('--password-stdin')) return { password: generatePassword(), generated: true };
  const password = (await io.readStdin()).replace(/\r?\n$/, '');
  if (password.length < MIN_PASSWORD_LENGTH || password.length > MAX_PASSWORD_LENGTH) {
    throw new UserError(
      `A password must be ${MIN_PASSWORD_LENGTH}-${MAX_PASSWORD_LENGTH} characters.`,
    );
  }
  return { password, generated: false };
}

/** Returns the process exit code. */
export async function runCli(argv: string[], db: Db, io: CliIo): Promise<number> {
  const flags = argv.filter(a => a.startsWith('--'));
  const [command, ...args] = argv.filter(a => !a.startsWith('--'));
  try {
    switch (command) {
      case 'add': {
        const [email, ...nameParts] = args;
        if (!email || !nameParts.length) break;
        const { password, generated } = await passwordFrom(flags, io);
        await addUser(db, { email, name: nameParts.join(' '), password });
        io.out(`Added ${email.trim().toLowerCase()}.`);
        if (generated) io.out(`Password (shown once, hand it over directly): ${password}`);
        return 0;
      }
      case 'set-password': {
        const [email] = args;
        if (!email) break;
        const { password, generated } = await passwordFrom(flags, io);
        const ended = await setPassword(db, email, password);
        io.out(`Password replaced; ${ended} session(s) ended.`);
        if (generated) io.out(`Password (shown once, hand it over directly): ${password}`);
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
          const status = u.disabledAt ? 'disabled' : u.hasPassword ? 'active' : 'no password';
          io.out(`${u.email}\t${u.name}\t${status}\t${u.sessions} session(s)`);
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
