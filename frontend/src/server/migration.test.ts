import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import type { PGlite } from '@electric-sql/pglite';

import { MIGRATION, freshDb } from './testing/pglite';

let pg: PGlite;

beforeAll(async () => {
  pg = (await freshDb()).pg;
});
afterAll(() => pg.close());

const insertUser = (email: string, name = 'X') =>
  pg.query('insert into ask_naren.users (email, name) values ($1, $2)', [email, name]);

describe('migrations', () => {
  it('is idempotent: applying it again is harmless', async () => {
    await expect(pg.exec(MIGRATION)).resolves.toBeDefined();
  });

  it('creates nothing outside the ask_naren schema, where Brain lives', async () => {
    const { rows } = await pg.query<{ table_schema: string; table_name: string }>(
      `select table_schema, table_name from information_schema.tables
       where table_schema not in ('pg_catalog', 'information_schema')`,
    );
    expect(rows.map(r => `${r.table_schema}.${r.table_name}`).sort()).toEqual([
      'ask_naren.sessions',
      'ask_naren.threads',
      'ask_naren.turns',
      'ask_naren.users',
    ]);
  });

  it('holds users to lower-case @joveo.com emails and a real name', async () => {
    await expect(insertUser('Priya@joveo.com')).rejects.toThrow();
    await expect(insertUser('priya@gmail.com')).rejects.toThrow();
    await expect(insertUser('priya@notjoveo.com')).rejects.toThrow();
    await expect(insertUser('priya@joveo.com', '   ')).rejects.toThrow();
    await insertUser('priya@joveo.com');
    await expect(insertUser('priya@joveo.com')).rejects.toThrow();
  });

  it('allows a user with no password -- the state after the Workspace cutover', async () => {
    await expect(insertUser('nopw@joveo.com')).resolves.toBeDefined();
  });

  it('keeps google_sub unique so one Google identity cannot map to two users', async () => {
    await pg.query(`insert into ask_naren.users (email, name, google_sub) values ('a@joveo.com', 'A', 's1')`);
    await expect(
      pg.query(`insert into ask_naren.users (email, name, google_sub) values ('b@joveo.com', 'B', 's1')`),
    ).rejects.toThrow();
  });

  it('refuses a session row that is not a SHA-256 hex digest', async () => {
    const { rows } = await pg.query<{ id: number }>(
      `insert into ask_naren.users (email, name) values ('s@joveo.com', 'S') returning id`,
    );
    await expect(
      pg.query(
        `insert into ask_naren.sessions values ('raw-token', $1, now(), now(), now())`,
        [rows[0].id],
      ),
    ).rejects.toThrow();
  });
});
