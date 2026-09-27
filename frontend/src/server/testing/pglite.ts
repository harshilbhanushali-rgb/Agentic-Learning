import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { PGlite } from '@electric-sql/pglite';

import type { Db } from '../db';

const MIGRATIONS_DIR = fileURLToPath(new URL('../../../db/migrations/', import.meta.url));

/** Every migration file, in order, as shipped -- not copies: the tests fail if the DDL an
 *  operator will run is wrong. */
export const MIGRATION = readdirSync(MIGRATIONS_DIR)
  .filter(f => f.endsWith('.sql'))
  .sort()
  .map(f => readFileSync(join(MIGRATIONS_DIR, f), 'utf8'))
  .join('\n');

/** Real Postgres, in-process, with the Ask Naren tables created by the shipped migrations. */
export async function freshDb(): Promise<{ pg: PGlite; db: Db; reset: () => Promise<void> }> {
  const pg = new PGlite();
  await pg.exec(MIGRATION);
  const db: Db = { query: (text, params) => pg.query(text, params) };
  const reset = async () => {
    await pg.exec('truncate ask_naren.turns, ask_naren.threads, ask_naren.sessions, ask_naren.users restart identity cascade');
  };
  return { pg, db, reset };
}
