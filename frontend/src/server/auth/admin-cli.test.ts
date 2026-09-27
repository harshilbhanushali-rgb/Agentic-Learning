import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import type { Db } from '../db';
import { freshDb } from '../testing/pglite';
import { runCli } from './admin-cli';
import { authenticate, listUsers } from './users';

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

async function run(argv: string[], stdin = '') {
  const lines: string[] = [];
  const code = await runCli(argv, db, { out: l => lines.push(l), readStdin: async () => stdin });
  return { code, output: lines.join('\n') };
}

const generated = (output: string) => /hand it over directly\): (\S+)/.exec(output)?.[1];

describe('users CLI', () => {
  it('add prints a generated password once, and that password signs in', async () => {
    const { code, output } = await run(['add', 'Priya@joveo.com', 'Priya', 'Shah']);
    expect(code).toBe(0);
    const pw = generated(output);
    expect(pw).toHaveLength(24);
    expect(await authenticate(db, 'priya@joveo.com', pw!)).not.toBeNull();
    expect((await listUsers(db))[0].name).toBe('Priya Shah');
  });

  it('takes a chosen password from stdin, never from an argument', async () => {
    const { code, output } = await run(['add', 'priya@joveo.com', 'Priya', '--password-stdin'], 'chosen-password-1\n');
    expect(code).toBe(0);
    expect(output).not.toContain('chosen-password-1');
    expect(generated(output)).toBeUndefined();
    expect(await authenticate(db, 'priya@joveo.com', 'chosen-password-1')).not.toBeNull();
  });

  it('refuses a short chosen password', async () => {
    const { code, output } = await run(['add', 'priya@joveo.com', 'Priya', '--password-stdin'], 'short');
    expect(code).toBe(1);
    expect(output).toContain('12-1024 characters');
    expect(await listUsers(db)).toHaveLength(0);
  });

  it('set-password, disable, enable, sign-out and list work end to end', async () => {
    await run(['add', 'priya@joveo.com', 'Priya']);
    const reset = await run(['set-password', 'priya@joveo.com']);
    expect(reset.output).toContain('0 session(s) ended');
    expect(await authenticate(db, 'priya@joveo.com', generated(reset.output)!)).not.toBeNull();

    expect((await run(['disable', 'priya@joveo.com'])).output).toContain('Disabled');
    expect((await run(['list'])).output).toContain('priya@joveo.com\tPriya\tdisabled\t0 session(s)');
    expect((await run(['enable', 'priya@joveo.com'])).code).toBe(0);
    expect((await run(['sign-out', 'priya@joveo.com'])).output).toBe('0 session(s) ended.');
    expect((await run(['list'])).output).toContain('\tactive\t');
  });

  it('reports a user error with exit code 1, and bad usage with 2', async () => {
    expect((await run(['add', 'priya@gmail.com', 'Priya'])).code).toBe(1);
    expect((await run(['disable', 'nobody@joveo.com'])).code).toBe(1);
    const usage = await run(['frobnicate']);
    expect(usage.code).toBe(2);
    expect(usage.output).toContain('Usage: npm run users');
    expect((await run(['add', 'priya@joveo.com'])).code).toBe(2);
  });
});
