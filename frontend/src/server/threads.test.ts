import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import type { AskNarenResponse } from '@/types';

import type { Db } from './db';
import { freshDb } from './testing/pglite';
import {
  deleteThread,
  extractColumns,
  listThreads,
  loadThread,
  recordTurn,
  renameThread,
} from './threads';

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

const T0 = new Date('2026-09-28T09:00:00Z');
const at = (s: number) => new Date(T0.getTime() + s * 1000);

const ANSWERED = {
  outcome: 'answered',
  intake: { intent: 'reply_to_client', retrieval_query: 'how long does ats take' },
  answer: 'He shrinks the ask.',
  quote: 'a couple of hours',
  citation: { label: 'call.txt', call_filename: 'call.txt', pair_id: 7, scenario_key: 'ats_integration' },
  match: { cosine: 0.83, scenario_key: 'ats_integration', rank: 1 },
} as AskNarenResponse;

const DECLINED = {
  outcome: 'declined',
  intake: { intent: 'reply_to_client', retrieval_query: 'pause spend' },
  reason: 'no_close_match',
  message: 'Nothing close.',
  match: { cosine: 0.61, scenario_key: 'budget_setup', rank: 1 },
} as AskNarenResponse;

const SEQUENCE = {
  outcome: 'rendered',
  kind: 'sequence',
  intake: { intent: 'sequence', retrieval_query: 'q' },
  scenario_key: 'xml_feed',
  steps: ['a', 'b'],
} as AskNarenResponse;

const CALL_PREP = {
  outcome: 'rendered',
  kind: 'call_prep',
  asked_about: 'kickoff',
  scenarios: [{ scenario_key: 'a' }, { scenario_key: 'b' }],
  scenarios_found: 2,
  exchanges: 3,
  basis: 'b',
} as unknown as AskNarenResponse;

const CLARIFY = { outcome: 'clarify', question: 'What did the client say?' } as AskNarenResponse;

async function seedUser(email = 'priya@joveo.com'): Promise<number> {
  const { rows } = await db.query<{ id: number }>(
    `insert into ask_naren.users (email, name, password_hash) values ($1, 'P', 'x') returning id`,
    [email],
  );
  return rows[0].id;
}

const ask = (userId: number, threadId: number | null, question: string, response: AskNarenResponse, s = 0) =>
  recordTurn(db, { userId, threadId, question, response, askedAt: at(s), answeredAt: at(s + 12) });

describe('extractColumns', () => {
  it('pulls each field from wherever the arm keeps it', () => {
    expect(extractColumns(ANSWERED)).toEqual({
      outcome: 'answered', kind: null, reason: null, intent: 'reply_to_client',
      scenarioKey: 'ats_integration', cosine: 0.83,
    });
    expect(extractColumns(DECLINED)).toMatchObject({ reason: 'no_close_match', scenarioKey: 'budget_setup', cosine: 0.61 });
    expect(extractColumns(SEQUENCE)).toMatchObject({ kind: 'sequence', scenarioKey: 'xml_feed', cosine: null });
    expect(extractColumns(CALL_PREP)).toMatchObject({ kind: 'call_prep', scenarioKey: null, intent: null });
    expect(extractColumns(CLARIFY)).toEqual({
      outcome: 'clarify', kind: null, reason: null, intent: null, scenarioKey: null, cosine: null,
    });
  });

  it('reads a follow-up answer (no match) from its citation', () => {
    const { match: _m, ...followUp } = ANSWERED as { match?: unknown };
    void _m;
    expect(extractColumns(followUp as AskNarenResponse)).toMatchObject({ scenarioKey: 'ats_integration', cosine: null });
  });
});

describe('recordTurn', () => {
  it('creates a thread on the first ask, then continues it in order', async () => {
    const u = await seedUser();
    const first = await ask(u, null, 'How long does ATS take?', ANSWERED);
    expect(first).toEqual({ threadId: expect.any(Number), position: 1 });
    const second = await ask(u, first!.threadId, 'And if IT pushes back?', DECLINED, 60);
    expect(second).toEqual({ threadId: first!.threadId, position: 2 });

    const { rows } = await db.query<Record<string, unknown>>(
      'select position, outcome, reason, intent, scenario_key, cosine from ask_naren.turns order by position',
    );
    expect(rows).toEqual([
      { position: 1, outcome: 'answered', reason: null, intent: 'reply_to_client', scenario_key: 'ats_integration', cosine: expect.closeTo(0.83, 5) },
      { position: 2, outcome: 'declined', reason: 'no_close_match', intent: 'reply_to_client', scenario_key: 'budget_setup', cosine: expect.closeTo(0.61, 5) },
    ]);
  });

  it('keeps the response verbatim', async () => {
    const u = await seedUser();
    const { threadId } = (await ask(u, null, 'q', ANSWERED))!;
    expect((await loadThread(db, u, threadId))!.turns[0].response).toEqual(ANSWERED);
  });

  it("refuses someone else's thread and a deleted one, writing nothing", async () => {
    const priya = await seedUser();
    const rahul = await seedUser('rahul@joveo.com');
    const { threadId } = (await ask(priya, null, 'q', ANSWERED))!;
    expect(await ask(rahul, threadId, 'mine now?', ANSWERED)).toBeNull();
    await deleteThread(db, priya, threadId);
    expect(await ask(priya, threadId, 'after delete', ANSWERED)).toBeNull();
    const { rows } = await db.query('select 1 from ask_naren.turns');
    expect(rows).toHaveLength(1);
  });

  it('records two asks racing into one thread, with distinct positions', async () => {
    const u = await seedUser();
    const { threadId } = (await ask(u, null, 'q1', ANSWERED))!;
    const [a, b] = await Promise.all([ask(u, threadId, 'tab A', ANSWERED), ask(u, threadId, 'tab B', DECLINED)]);
    expect([a!.position, b!.position].sort()).toEqual([2, 3]);
  });

  it('a user with threads cannot be deleted by accident', async () => {
    const u = await seedUser();
    await ask(u, null, 'q', ANSWERED);
    await expect(db.query('delete from ask_naren.users where id = $1', [u])).rejects.toThrow();
  });
});

describe('listing, loading, renaming, deleting', () => {
  it('lists own threads newest first, titled by the first question unless renamed', async () => {
    const priya = await seedUser();
    const rahul = await seedUser('rahul@joveo.com');
    const older = (await ask(priya, null, 'Client is moving their XML feed', SEQUENCE, 0))!.threadId;
    const newer = (await ask(priya, null, 'On today’s kickoff their TA lead said…', ANSWERED, 100))!.threadId;
    await ask(rahul, null, 'not yours', ANSWERED, 200);
    await ask(priya, older, 'follow-up that should not retitle it', CLARIFY, 50);
    await renameThread(db, priya, newer, 'Northwind — ATS timeline');

    const list = await listThreads(db, priya);
    expect(list.map(t => [t.id, t.title, t.renamed, t.turnCount])).toEqual([
      [newer, 'Northwind — ATS timeline', true, 1],
      [older, 'Client is moving their XML feed', false, 2],
    ]);
  });

  it('loads turns in order, and only for the owner', async () => {
    const priya = await seedUser();
    const rahul = await seedUser('rahul@joveo.com');
    const { threadId } = (await ask(priya, null, 'first', ANSWERED))!;
    await ask(priya, threadId, 'second', CLARIFY, 30);
    const thread = await loadThread(db, priya, threadId);
    expect(thread!.turns.map(t => [t.position, t.question])).toEqual([[1, 'first'], [2, 'second']]);
    expect(thread!.turns[1].askedAt).toEqual(at(30));
    expect(await loadThread(db, rahul, threadId)).toBeNull();
    expect(await loadThread(db, priya, 999_999)).toBeNull();
  });

  it('renames, trims, caps at 120, and clears back to the derived title', async () => {
    const u = await seedUser();
    const { threadId } = (await ask(u, null, 'derived', ANSWERED))!;
    await renameThread(db, u, threadId, `  ${'x'.repeat(200)}  `);
    expect((await listThreads(db, u))[0].title).toHaveLength(120);
    await renameThread(db, u, threadId, '   ');
    expect((await listThreads(db, u))[0]).toMatchObject({ title: 'derived', renamed: false });
    expect(await renameThread(db, await seedUser('rahul@joveo.com'), threadId, 'hijack')).toBe(false);
  });

  it('removes from the list without erasing the rows', async () => {
    const u = await seedUser();
    const { threadId } = (await ask(u, null, 'q', ANSWERED))!;
    expect(await deleteThread(db, await seedUser('rahul@joveo.com'), threadId)).toBe(false);
    expect(await deleteThread(db, u, threadId)).toBe(true);
    expect(await deleteThread(db, u, threadId)).toBe(false);
    expect(await listThreads(db, u)).toEqual([]);
    expect(await loadThread(db, u, threadId)).toBeNull();
    const { rows } = await db.query('select 1 from ask_naren.turns where thread_id = $1', [threadId]);
    expect(rows).toHaveLength(1);
  });
});
