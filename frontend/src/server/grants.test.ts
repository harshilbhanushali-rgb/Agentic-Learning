import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import type { PGlite } from '@electric-sql/pglite';

import type { AskNarenResponse } from '@/types';

import type { Db } from './db';
import { PrivilegeError, assertLeastPrivilege } from './privilege';
import { freshDb } from './testing/pglite';
import { createSession, deleteSession, validateSession } from './auth/sessions';
import {
  addUser,
  authenticate,
  disableUser,
  enableUser,
  listUsers,
  setPassword,
  signOutEverywhere,
} from './auth/users';
import { deleteThread, listThreads, loadThread, recordTurn, renameThread } from './threads';

/**
 * The grants in db/provision/, exercised by the code that depends on them (issue #47).
 *
 * Every function the web app and the CLI call runs here AS the SQL-created role it runs as
 * in production. A grant that is missing fails here as "permission denied" rather than on a
 * CSM's first request; a grant that is too wide fails the "cannot" half.
 */
const provision = (file: string) =>
  readFileSync(fileURLToPath(new URL(`../../db/provision/${file}`, import.meta.url)), 'utf8');

let pg: PGlite;
let owner: Db;
let reset: () => Promise<void>;

/** A Db that runs each query as `role`. PGlite is one connection, and these tests are serial. */
function as(role: string): Db {
  return {
    query: async (text, params) => {
      await pg.exec(`set role ${role}`);
      try {
        return await pg.query(text, params);
      } finally {
        await pg.exec('reset role');
      }
    },
  };
}

const app = () => as('ask_naren_app');
const admin = () => as('ask_naren_admin');

beforeAll(async () => {
  const fresh = await freshDb();
  pg = fresh.pg;
  owner = fresh.db;
  reset = fresh.reset;
  // Brain's side of the instance, which neither role may touch.
  await pg.exec('create table public.kb_pairs (id int primary key, client_turn text)');
  await pg.exec(provision('roles.sql'));
  await pg.exec(provision('grants.sql'));
  // Re-running both must be harmless: provisioning is idempotent.
  await pg.exec(provision('roles.sql'));
  await pg.exec(provision('grants.sql'));
});
afterAll(() => pg.close());
beforeEach(() => reset());

const ANSWER = {
  outcome: 'answered',
  answer: 'a',
  quote: 'q',
  citation: { label: 'c', call_filename: 'c', scenario_key: 's' },
  match: { cosine: 0.8, scenario_key: 's', rank: 1 },
} as AskNarenResponse;

const denied = expect.objectContaining({ message: expect.stringMatching(/permission denied/) });

describe('ask_naren_admin (the users CLI)', () => {
  it('can do everything the CLI does', async () => {
    await addUser(admin(), { email: 'priya@joveo.com', name: 'Priya', password: 'pw-for-tests-1' });
    expect(await setPassword(admin(), 'priya@joveo.com', 'pw-for-tests-2')).toBe(0);
    await disableUser(admin(), 'priya@joveo.com');
    await enableUser(admin(), 'priya@joveo.com');
    expect(await signOutEverywhere(admin(), 'priya@joveo.com')).toBe(0);
    expect((await listUsers(admin()))[0]).toMatchObject({ email: 'priya@joveo.com', sessions: 0 });
  });

  it("cannot read threads, turns, or Brain's tables", async () => {
    await expect(admin().query('select * from ask_naren.threads')).rejects.toEqual(denied);
    await expect(admin().query('select * from ask_naren.turns')).rejects.toEqual(denied);
    await expect(admin().query('select * from public.kb_pairs')).rejects.toEqual(denied);
  });
});

describe('ask_naren_app (the web app)', () => {
  it('can sign in, keep a session, and read and write threads', async () => {
    const id = await addUser(admin(), { email: 'priya@joveo.com', name: 'Priya', password: 'pw-for-tests-1' });
    expect(await authenticate(app(), 'priya@joveo.com', 'pw-for-tests-1')).toEqual({ id });
    const t0 = new Date('2026-09-28T09:00:00Z');
    const { token } = await createSession(app(), id, t0);
    // Two hours later: the lookup AND the last_seen touch both run as the app. The touch is
    // housekeeping -- a failure is swallowed at runtime (issue #40) -- so a missing grant would
    // be silent there. Read the row back to prove the write really happened.
    const later = new Date(t0.getTime() + 2 * 3600e3);
    expect(await validateSession(app(), token, later)).not.toBeNull();
    const { rows } = await owner.query<{ last_seen_at: Date }>('select last_seen_at from ask_naren.sessions');
    expect(new Date(rows[0].last_seen_at)).toEqual(later);

    const first = await recordTurn(app(), {
      userId: id, threadId: null, question: 'q1', response: ANSWER, askedAt: t0, answeredAt: t0,
    });
    await recordTurn(app(), {
      userId: id, threadId: first!.threadId, question: 'q2', response: ANSWER, askedAt: t0, answeredAt: t0,
    });
    expect(await listThreads(app(), id)).toHaveLength(1);
    expect((await loadThread(app(), id, first!.threadId))!.turns).toHaveLength(2);
    expect(await renameThread(app(), id, first!.threadId, 'Renamed')).toBe(true);
    expect(await deleteThread(app(), id, first!.threadId)).toBe(true);
    await deleteSession(app(), token);
  });

  it('cannot create a user or set a password -- that is the admin credential', async () => {
    await expect(
      app().query(`insert into ask_naren.users (email, name, password_hash) values ('x@joveo.com', 'X', 'h')`),
    ).rejects.toEqual(denied);
    await addUser(admin(), { email: 'priya@joveo.com', name: 'Priya', password: 'pw-for-tests-1' });
    await expect(app().query(`update ask_naren.users set password_hash = 'h'`)).rejects.toEqual(denied);
    await expect(app().query(`update ask_naren.users set disabled_at = null`)).rejects.toEqual(denied);
  });

  it('cannot rewrite history: turns are append-only, threads are never hard-deleted', async () => {
    const id = await addUser(admin(), { email: 'priya@joveo.com', name: 'Priya', password: 'pw-for-tests-1' });
    const t0 = new Date();
    await recordTurn(app(), { userId: id, threadId: null, question: 'q', response: ANSWER, askedAt: t0, answeredAt: t0 });
    await expect(app().query(`update ask_naren.turns set question = 'edited'`)).rejects.toEqual(denied);
    await expect(app().query('delete from ask_naren.turns')).rejects.toEqual(denied);
    await expect(app().query('delete from ask_naren.threads')).rejects.toEqual(denied);
    await expect(app().query('update ask_naren.threads set user_id = 1')).rejects.toEqual(denied);
  });

  it("cannot read or write Brain's tables, or create anything", async () => {
    await expect(app().query('select * from public.kb_pairs')).rejects.toEqual(denied);
    await expect(app().query(`insert into public.kb_pairs values (1, 'x')`)).rejects.toEqual(denied);
    await expect(app().query('create schema sneaky')).rejects.toEqual(denied);
    await expect(app().query('create table ask_naren.sneaky (id int)')).rejects.toEqual(denied);
  });
});

describe('the startup privilege check', () => {
  it('passes for both SQL-created roles', async () => {
    await expect(assertLeastPrivilege(app())).resolves.toBeUndefined();
    await expect(assertLeastPrivilege(admin())).resolves.toBeUndefined();
  });

  it('refuses a superuser -- the owner credential Brain itself uses', async () => {
    const quiet = console.error;
    console.error = () => {};
    try {
      await expect(assertLeastPrivilege(owner)).rejects.toThrow(PrivilegeError);
      await expect(assertLeastPrivilege(owner)).rejects.toThrow(/is a superuser/);
    } finally {
      console.error = quiet;
    }
  });

  it('refuses a role that can read kb_pairs, however it got there', async () => {
    await pg.exec('create role leaky login nosuperuser; grant select on public.kb_pairs to leaky');
    const quiet = console.error;
    console.error = () => {};
    try {
      await expect(assertLeastPrivilege(as('leaky'))).rejects.toThrow(/can read Brain's public.kb_pairs/);
    } finally {
      console.error = quiet;
    }
  });
});
