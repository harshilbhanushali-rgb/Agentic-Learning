// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

/* `pg` is replaced by a pool that records what it was built with and answers from a queue,
 * so nothing here opens a connection. What is under test is the seam's own logic: one pool
 * per role, the env var read at first use, and the least-privilege check gating the first
 * query -- with only a PASS remembered. */
const pg = vi.hoisted(() => ({
  configs: [] as unknown[],
  query: null as unknown as ReturnType<typeof import('vitest').vi.fn>,
}));
vi.mock('pg', () => ({
  Pool: class {
    constructor(config: unknown) {
      pg.configs.push(config);
    }
    query(text: string, params?: unknown[]) {
      return pg.query(text, params);
    }
  },
}));

const assertLeastPrivilege = vi.fn<(db: unknown) => Promise<void>>();
vi.mock('./privilege', () => ({ assertLeastPrivilege: (db: unknown) => assertLeastPrivilege(db) }));

const { adminDb, db } = await import('./db');

const pools = () => (globalThis as unknown as { askNarenPools?: Map<string, unknown> }).askNarenPools;

beforeEach(() => {
  pools()?.clear();
  pg.configs.length = 0;
  pg.query = vi.fn(async () => ({ rows: [{ ok: 1 }] }));
  assertLeastPrivilege.mockReset();
  assertLeastPrivilege.mockResolvedValue(undefined);
  vi.stubEnv('ASK_NAREN_DATABASE_URL', 'postgres://app@example.invalid/db');
  vi.stubEnv('ASK_NAREN_ADMIN_DATABASE_URL', 'postgres://admin@example.invalid/db');
  vi.stubEnv('ASK_NAREN_SKIP_PRIVILEGE_CHECK', '');
});

describe('db()', () => {
  it('builds one bounded pool per role per process', () => {
    const a = db();
    expect(db()).toBe(a);
    expect(adminDb()).not.toBe(a);
    expect(pg.configs).toEqual([
      expect.objectContaining({
        connectionString: 'postgres://app@example.invalid/db',
        max: 5,
        connectionTimeoutMillis: 5_000,
        query_timeout: 10_000,
      }),
      expect.objectContaining({ connectionString: 'postgres://admin@example.invalid/db' }),
    ]);
  });

  it('throws on first use, naming the variable, when it is not set', () => {
    vi.stubEnv('ASK_NAREN_DATABASE_URL', '');
    expect(() => db()).toThrow(/ASK_NAREN_DATABASE_URL is not set\. Sign-in needs/);
    vi.stubEnv('ASK_NAREN_ADMIN_DATABASE_URL', '');
    expect(() => adminDb()).toThrow(/ASK_NAREN_ADMIN_DATABASE_URL is not set\. The users CLI needs/);
  });

  it('checks the role once, before the first query, and remembers a pass', async () => {
    const d = db();
    expect(await d.query('select 1', [1])).toEqual({ rows: [{ ok: 1 }] });
    await d.query('select 2');
    expect(assertLeastPrivilege).toHaveBeenCalledTimes(1);
    expect(pg.query).toHaveBeenCalledWith('select 1', [1]);
  });

  it('refuses to query as an over-privileged role, and checks again next time', async () => {
    assertLeastPrivilege.mockRejectedValueOnce(new Error('Refusing to use database role'));
    const d = db();
    await expect(d.query('select 1')).rejects.toThrow('Refusing to use database role');
    expect(pg.query).not.toHaveBeenCalled();

    // A transient failure must not wedge the process: the next query runs the check again.
    expect(await d.query('select 1')).toEqual({ rows: [{ ok: 1 }] });
    expect(assertLeastPrivilege).toHaveBeenCalledTimes(2);
  });

  it('skips the check only outside production, and only when asked', async () => {
    vi.stubEnv('ASK_NAREN_SKIP_PRIVILEGE_CHECK', '1');
    vi.stubEnv('NODE_ENV', 'development');
    await db().query('select 1');
    expect(assertLeastPrivilege).not.toHaveBeenCalled();

    pools()?.clear();
    vi.stubEnv('NODE_ENV', 'production');
    await db().query('select 1');
    expect(assertLeastPrivilege).toHaveBeenCalledTimes(1);
  });
});
