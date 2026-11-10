// @vitest-environment node
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import type { Db } from '../db';
import { freshDb } from '../testing/pglite';
import { runCli } from './admin-cli';
import { authenticateGoogle, listUsers } from './users';

let db: Db;
let reset: () => Promise<void>;
let close: () => Promise<void>;

beforeAll(async () => {
  const fresh = await freshDb();
  db = fresh.db;
  reset = fresh.reset;
  close = () => fresh.pg.close();
});
afterAll(() => close());
beforeEach(() => reset());

async function run(argv: string[]) {
  const lines: string[] = [];
  const code = await runCli(argv, db, { out: l => lines.push(l) });
  return { code, output: lines.join('\n') };
}

describe('users CLI', () => {
  it('add creates a member who can then sign in with Google, and prints no password', async () => {
    const { code, output } = await run(['add', 'Priya@joveo.com', 'Priya', 'Shah']);
    expect(code).toBe(0);
    expect(output).toBe('Added priya@joveo.com. They sign in with Google.');
    expect((await listUsers(db))[0]).toMatchObject({ name: 'Priya Shah', role: 'member' });
    expect(await authenticateGoogle(db, { sub: 'g-priya', email: 'priya@joveo.com' })).not.toBeNull();
  });

  it('role makes someone an admin or a member', async () => {
    await run(['add', 'priya@joveo.com', 'Priya']);
    expect((await run(['role', 'priya@joveo.com', 'admin'])).output).toBe('priya@joveo.com is now an admin.');
    expect((await listUsers(db))[0].role).toBe('admin');
    expect((await run(['role', 'priya@joveo.com', 'member'])).output).toBe('priya@joveo.com is now a member.');
    expect((await run(['role', 'priya@joveo.com', 'owner'])).code).toBe(1);
  });

  it('disable, enable, sign-out and list work end to end', async () => {
    await run(['add', 'priya@joveo.com', 'Priya']);
    expect((await run(['disable', 'priya@joveo.com'])).output).toContain('Disabled');
    expect((await run(['list'])).output).toContain('priya@joveo.com\tPriya\tmember\tdisabled\t0 session(s)');
    expect((await run(['enable', 'priya@joveo.com'])).code).toBe(0);
    expect((await run(['sign-out', 'priya@joveo.com'])).output).toBe('0 session(s) ended.');
    expect((await run(['list'])).output).toContain('\tmember\tnot signed in yet\t');
  });

  it('reports a user error with exit code 1, and bad usage with 2', async () => {
    expect((await run(['add', 'priya@gmail.com', 'Priya'])).code).toBe(1);
    expect((await run(['disable', 'nobody@joveo.com'])).code).toBe(1);
    const usage = await run(['set-password', 'priya@joveo.com']);
    expect(usage.code).toBe(2);
    expect(usage.output).toContain('Usage: npm run users');
    expect((await run(['add', 'priya@joveo.com'])).code).toBe(2);
  });
});
