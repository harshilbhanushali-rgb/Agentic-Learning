import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { PGlite } from '@electric-sql/pglite';

import type { Db } from '../db';

/** The migration file itself, not a copy: the tests fail if the shipped DDL is wrong. */
export const MIGRATION = readFileSync(
  fileURLToPath(new URL('../../../db/migrations/0001_users_and_sessions.sql', import.meta.url)),
  'utf8',
);

/** Real Postgres, in-process, with the Ask Naren tables created by the shipped migration. */
export async function freshDb(): Promise<{ pg: PGlite; db: Db; reset: () => Promise<void> }> {
  const pg = new PGlite();
  await pg.exec(MIGRATION);
  const db: Db = { query: (text, params) => pg.query(text, params) };
  const reset = async () => {
    await pg.exec('truncate ask_naren.sessions, ask_naren.users restart identity cascade');
  };
  return { pg, db, reset };
}
