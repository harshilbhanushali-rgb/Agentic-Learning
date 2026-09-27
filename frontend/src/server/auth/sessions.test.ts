import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Db } from '../db';
import { freshDb } from '../testing/pglite';
import {
  ABSOLUTE_MS,
  IDLE_MS,
  TOUCH_INTERVAL_MS,
  createSession,
  deleteSession,
  deleteUserSessions,
  hashToken,
  validateSession,
} from './sessions';

let db: Db;
let reset: () => Promise<void>;
let close: () => Promise<void>;

const T0 = new Date('2026-09-27T09:00:00Z');
const at = (ms: number) => new Date(T0.getTime() + ms);

async function seedUser(email = 'priya@joveo.com', name = 'Priya'): Promise<number> {
  const { rows } = await db.query<{ id: number }>(
    `insert into ask_naren.users (email, name, password_hash) values ($1, $2, 'x') returning id`,
    [email, name],
  );
  return rows[0].id;
}

async function sessionRows() {
  return (await db.query<Record<string, unknown>>('select * from ask_naren.sessions')).rows;
}

beforeAll(async () => {
  const fresh = await freshDb();
  db = fresh.db;
  reset = fresh.reset;
  close = () => fresh.pg.close();
});
afterAll(() => close());
beforeEach(() => reset());

describe('sessions', () => {
  it('a new session resolves to its user', async () => {
    const id = await seedUser();
    const { token, expiresAt } = await createSession(db, id, T0);
    expect(expiresAt).toEqual(at(ABSOLUTE_MS));
    expect(await validateSession(db, token, at(1000))).toEqual({
      id,
      email: 'priya@joveo.com',
      name: 'Priya',
    });
  });

  it('stores only the SHA-256 of the token, so the table does not yield a sign-in', async () => {
    const { token } = await createSession(db, await seedUser(), T0);
    const rows = await sessionRows();
    expect(rows).toHaveLength(1);
    expect(rows[0].token_hash).toBe(hashToken(token));
    expect(JSON.stringify(rows)).not.toContain(token);
  });

  it('issues a distinct 256-bit token each time', async () => {
    const id = await seedUser();
    const a = await createSession(db, id, T0);
    const b = await createSession(db, id, T0);
    expect(a.token).not.toBe(b.token);
    expect(Buffer.from(a.token, 'base64url')).toHaveLength(32);
  });

  it('ignores a missing, malformed or unknown token without touching the database', async () => {
    await seedUser();
    const queries: string[] = [];
    const spy: Db = { query: (t, p) => (queries.push(t), db.query(t, p)) };
    expect(await validateSession(spy, undefined, T0)).toBeNull();
    expect(await validateSession(spy, '', T0)).toBeNull();
    expect(await validateSession(spy, "x' or 1=1 --", T0)).toBeNull();
    expect(queries).toHaveLength(0);
    expect(await validateSession(db, 'A'.repeat(43), T0)).toBeNull();
  });

  it('ends after 14 days unused, and deletes the row', async () => {
    const id = await seedUser();
    const justInside = await createSession(db, id, T0);
    const unused = await createSession(db, id, T0);
    expect(await validateSession(db, justInside.token, at(IDLE_MS - 1))).not.toBeNull();
    expect(await validateSession(db, unused.token, at(IDLE_MS))).toBeNull();
    const remaining = (await sessionRows()).map(r => r.token_hash);
    expect(remaining).toEqual([hashToken(justInside.token)]);
  });

  it('use keeps it alive past 14 days, but never past 30', async () => {
    const { token } = await createSession(db, await seedUser(), T0);
    for (let day = 10; day < 30; day += 10) {
      expect(await validateSession(db, token, at(day * 24 * 3600 * 1000))).not.toBeNull();
    }
    expect(await validateSession(db, token, at(ABSOLUTE_MS - 1))).not.toBeNull();
    expect(await validateSession(db, token, at(ABSOLUTE_MS))).toBeNull();
    expect(await sessionRows()).toHaveLength(0);
  });

  it('writes last_seen at most hourly, not on every request', async () => {
    const { token } = await createSession(db, await seedUser(), T0);
    const lastSeen = async () => new Date((await sessionRows())[0].last_seen_at as Date).getTime();
    await validateSession(db, token, at(TOUCH_INTERVAL_MS - 1));
    expect(await lastSeen()).toBe(T0.getTime());
    await validateSession(db, token, at(TOUCH_INTERVAL_MS));
    expect(await lastSeen()).toBe(at(TOUCH_INTERVAL_MS).getTime());
  });

  it('a disabled user is signed out on their next request', async () => {
    const id = await seedUser();
    const { token } = await createSession(db, id, T0);
    await db.query('update ask_naren.users set disabled_at = now() where id = $1', [id]);
    expect(await validateSession(db, token, at(1000))).toBeNull();
    expect(await sessionRows()).toHaveLength(0);
  });

  it('signing out ends this browser only', async () => {
    const id = await seedUser();
    const laptop = await createSession(db, id, T0);
    const phone = await createSession(db, id, T0);
    await deleteSession(db, laptop.token);
    expect(await validateSession(db, laptop.token, at(1000))).toBeNull();
    expect(await validateSession(db, phone.token, at(1000))).not.toBeNull();
  });

  it('ending a user everywhere leaves other users signed in', async () => {
    const priya = await seedUser();
    const rahul = await seedUser('rahul@joveo.com', 'Rahul');
    await createSession(db, priya, T0);
    await createSession(db, priya, T0);
    const theirs = await createSession(db, rahul, T0);
    expect(await deleteUserSessions(db, priya)).toBe(2);
    expect(await validateSession(db, theirs.token, at(1000))).not.toBeNull();
  });

  it("a new sign-in sweeps that user's dead sessions", async () => {
    const id = await seedUser();
    await createSession(db, id, T0);
    await createSession(db, id, at(ABSOLUTE_MS + 1));
    expect(await sessionRows()).toHaveLength(1);
  });

  it('a database fault throws rather than reading as signed out', async () => {
    const { token } = await createSession(db, await seedUser(), T0);
    const broken: Db = { query: () => Promise.reject(new Error('connection refused')) };
    await expect(validateSession(broken, token, T0)).rejects.toThrow('connection refused');
  });
});

describe('when the store refuses writes', () => {
  it('a valid session still resolves: the touch and the sweep are housekeeping', async () => {
    const { token } = await createSession(db, await seedUser(), T0);
    const readOnly: Db = {
      query: (t, p) =>
        /^\s*(update|delete)/i.test(t) ? Promise.reject(new Error('read-only transaction')) : db.query(t, p),
    };
    const quiet = vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(await validateSession(readOnly, token, at(2 * TOUCH_INTERVAL_MS))).not.toBeNull();
    // A dead one is still refused even though its row could not be deleted.
    expect(await validateSession(readOnly, token, at(ABSOLUTE_MS))).toBeNull();
    quiet.mockRestore();
  });
});
