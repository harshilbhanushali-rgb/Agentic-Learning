import { Pool } from 'pg';

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

/* ONE POOL PER PROCESS, kept on globalThis because `next dev` re-evaluates modules on every
 * edit and a module-level pool would leak a new set of connections each time. */
const globalForDb = globalThis as unknown as { askNarenPool?: Pool };

/**
 * The app's connection to the Ask Naren tables in Brain's Neon instance.
 *
 * READ AT FIRST USE, NOT AT IMPORT, so pages that never touch sign-in (every page except
 * /ask-naren) keep working in an environment with no database configured. Throws rather
 * than falling back to a default: there is no sensible local default for a database, and a
 * silent one would read as "nobody is signed in" rather than as the misconfiguration it is.
 */
export function db(): Db {
  let pool = globalForDb.askNarenPool;
  if (!pool) {
    const connectionString = process.env.ASK_NAREN_DATABASE_URL;
    if (!connectionString) {
      throw new Error(
        'ASK_NAREN_DATABASE_URL is not set. Sign-in needs the Ask Naren tables -- see .env.example.',
      );
    }
    pool = new Pool({ connectionString, max: 5 });
    globalForDb.askNarenPool = pool;
  }
  const connected = pool;
  return {
    // The row type is the caller's claim about its own SQL; `pg` cannot check it either.
    query: <R,>(text: string, params?: unknown[]) =>
      connected.query(text, params) as unknown as Promise<{ rows: R[] }>,
  };
}
