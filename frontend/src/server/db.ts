import { Pool } from 'pg';

import { assertLeastPrivilege } from './privilege';

/**
 * The database seam for everything under src/server (issue #44).
 *
 * AN INTERFACE THIS NARROW ON PURPOSE. The sign-in code takes a `Db` rather than importing a
 * driver, so the tests run it against real Postgres (PGlite, in-process) and the app runs it
 * against `pg` -- one implementation of the logic, two drivers underneath it.
 */
export interface Db {
  query<R = Record<string, unknown>>(text: string, params?: unknown[]): Promise<{ rows: R[] }>;
}

/* ONE POOL PER ROLE PER PROCESS, kept on globalThis because `next dev` re-evaluates modules on
 * every edit and a module-level pool would leak a new set of connections each time. */
const globalForDb = globalThis as unknown as { askNarenPools?: Map<string, Db> };

/**
 * BOUNDED WAITS (issue #40), set well inside the proxy's 35s budget. Without them a hung Neon
 * or an exhausted pool is an endless "Searching Naren's calls…", and no error copy, however
 * well written, ever reaches the screen. `query_timeout` is enforced by the client rather than
 * as a server `statement_timeout`, because the app connects through Neon's pooler, where
 * session settings are unsafe (Brain/docs/GOTCHAS.md).
 */
const CONNECT_TIMEOUT_MS = 5_000;
const QUERY_TIMEOUT_MS = 10_000;

/**
 * THE LEAST-PRIVILEGE CHECK RUNS BEFORE THE FIRST QUERY (issue #38) and refuses to serve if
 * the role could reach Brain's pipeline. Skippable only outside production, for a local
 * database whose only role is a superuser (PGlite's socket server, a laptop Postgres).
 */
function privilegeCheckSkipped(): boolean {
  return process.env.NODE_ENV !== 'production' && process.env.ASK_NAREN_SKIP_PRIVILEGE_CHECK === '1';
}

function connect(envVar: string, what: string): Db {
  const pools = (globalForDb.askNarenPools ??= new Map());
  const existing = pools.get(envVar);
  if (existing) return existing;

  const connectionString = process.env[envVar];
  if (!connectionString) {
    throw new Error(`${envVar} is not set. ${what} needs the Ask Naren tables -- see .env.example.`);
  }
  const pool = new Pool({
    connectionString,
    max: 5,
    connectionTimeoutMillis: CONNECT_TIMEOUT_MS,
    query_timeout: QUERY_TIMEOUT_MS,
  });
  const raw: Db = {
    // The row type is the caller's claim about its own SQL; `pg` cannot check it either.
    query: <R,>(text: string, params?: unknown[]) =>
      pool.query(text, params) as unknown as Promise<{ rows: R[] }>,
  };

  // Only a PASS is remembered. A failed check -- over-privileged, or simply unreachable --
  // runs again on the next query, so a transient outage does not wedge the process.
  let checked: Promise<void> | undefined = privilegeCheckSkipped() ? Promise.resolve() : undefined;
  const guarded: Db = {
    query: async (text, params) => {
      if (!checked) {
        const attempt = assertLeastPrivilege(raw);
        checked = attempt;
        attempt.catch(() => {
          if (checked === attempt) checked = undefined;
        });
      }
      await checked;
      return raw.query(text, params);
    },
  };
  pools.set(envVar, guarded);
  return guarded;
}

/**
 * The web app's connection (role `ask_naren_app`).
 *
 * READ AT FIRST USE, NOT AT IMPORT, so pages that never touch sign-in (every page except
 * /ask-naren) keep working in an environment with no database configured. Throws rather
 * than falling back to a default: there is no sensible local default for a database, and a
 * silent one would read as "nobody is signed in" rather than as the misconfiguration it is.
 */
export function db(): Db {
  return connect('ASK_NAREN_DATABASE_URL', 'Sign-in');
}

/**
 * The admin CLI's connection (role `ask_naren_admin`, issue #38). A separate credential so
 * that the web app's cannot create a user or set a password -- a compromised app must not be
 * able to mint itself a permanent sign-in.
 */
export function adminDb(): Db {
  return connect('ASK_NAREN_ADMIN_DATABASE_URL', 'The users CLI');
}
