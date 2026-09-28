import { describe, it, expect, vi } from 'vitest';

import { answer, decline } from '../../../tests/fixtures/ask-naren';
import * as api from './threadClient';

/** A same-origin route's response, as the browser would see it. */
function reply(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status, headers });
}

function stubFetch(impl: () => Promise<Response>) {
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(impl);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const SUMMARY = {
  id: 4,
  title: 'Pausing spend',
  renamed: false,
  createdAt: '2026-09-01T10:00:00.000Z',
  lastTurnAt: '2026-09-01T10:00:00.000Z',
  turnCount: 1,
};

describe('the thread calls', () => {
  it('lists threads, uncached', async () => {
    const f = stubFetch(async () => reply({ threads: [SUMMARY] }));
    expect(await api.fetchThreads()).toEqual({ kind: 'ok', value: [SUMMARY] });
    expect(f).toHaveBeenCalledWith('/api/ask-naren/threads', { cache: 'no-store' });
  });

  it('fetches one thread by id', async () => {
    const thread = { ...SUMMARY, turns: [] };
    const f = stubFetch(async () => reply({ thread }));
    expect(await api.fetchThread(4)).toEqual({ kind: 'ok', value: thread });
    expect(f.mock.calls[0][0]).toBe('/api/ask-naren/threads/4');
  });

  it('renames with a PATCH carrying the title, and clears with null', async () => {
    const f = stubFetch(async () => reply({ thread: { ...SUMMARY, title: 'New', renamed: true } }));
    expect(await api.renameThread(4, 'New')).toEqual({
      kind: 'ok',
      value: { ...SUMMARY, title: 'New', renamed: true },
    });
    const init = f.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(init.body as string)).toEqual({ title: 'New' });

    await api.renameThread(4, null);
    expect(JSON.parse((f.mock.calls[1][1] as RequestInit).body as string)).toEqual({ title: null });
  });

  it('removes with a DELETE', async () => {
    const f = stubFetch(async () => reply({ ok: true }));
    expect(await api.removeThread(4)).toEqual({ kind: 'ok', value: true });
    expect((f.mock.calls[0][1] as RequestInit).method).toBe('DELETE');
  });

  /* Every status has exactly one meaning, whichever call returned it. */
  it.each([
    [401, 'signed_out'],
    [404, 'not_found'],
    [500, 'unavailable'],
    [503, 'unavailable'],
  ])('maps a %i to %s', async (status, kind) => {
    stubFetch(async () => reply({ error: 'x' }, status));
    expect(await api.fetchThreads()).toEqual({ kind });
    expect(await api.fetchThread(1)).toEqual({ kind });
    expect(await api.renameThread(1, 't')).toEqual({ kind });
    expect(await api.removeThread(1)).toEqual({ kind });
  });

  it('treats no response at all, or a body that is not JSON, as unavailable', async () => {
    stubFetch(async () => {
      throw new TypeError('network down');
    });
    expect(await api.fetchThreads()).toEqual({ kind: 'unavailable' });

    stubFetch(async () => reply('<html>proxy error</html>'));
    expect(await api.fetchThreads()).toEqual({ kind: 'unavailable' });
  });
});

describe('ask', () => {
  const RECORDED = { 'X-Ask-Naren-Thread': '9', 'X-Ask-Naren-Position': '2' };

  it('sends the situation and the thread id, never the thread itself', async () => {
    const f = stubFetch(async () => reply(answer(), 200, RECORDED));
    await api.ask('client says applies are flat', 9);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/ask-naren');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({
      situation: 'client says applies are flat',
      thread_id: 9,
    });
  });

  it('reads where a recorded turn went from the headers', async () => {
    stubFetch(async () => reply(answer(), 200, RECORDED));
    expect(await api.ask('q', null)).toEqual({
      kind: 'answered',
      result: answer(),
      recorded: true,
      threadId: 9,
      position: 2,
    });
  });

  it('reports an answer the store failed to record as recorded: false', async () => {
    stubFetch(async () => reply(answer(), 200, { ...RECORDED, 'X-Ask-Naren-Recorded': 'false' }));
    expect(await api.ask('q', 9)).toEqual({ kind: 'answered', result: answer(), recorded: false });
  });

  it('treats missing or nonsense headers as not recorded rather than inventing a thread', async () => {
    stubFetch(async () => reply(answer()));
    expect(await api.ask('q', null)).toMatchObject({ recorded: false });

    stubFetch(async () => reply(answer(), 200, { 'X-Ask-Naren-Thread': 'abc', 'X-Ask-Naren-Position': '1' }));
    expect(await api.ask('q', null)).toMatchObject({ recorded: false });
  });

  it('is signed_out on a 401, whatever the body', async () => {
    stubFetch(async () => reply('not json', 401));
    expect(await api.ask('q', null)).toEqual({ kind: 'signed_out' });
  });

  it('is thread_not_found on the route’s 404', async () => {
    stubFetch(async () => reply({ error: 'thread_not_found' }, 404));
    expect(await api.ask('q', 3)).toEqual({ kind: 'thread_not_found' });
  });

  it('does not ask again after a store fault: store_unavailable is not a turn', async () => {
    const body = decline('store_unavailable');
    stubFetch(async () => reply(body, 500));
    expect(await api.ask('q', 3)).toEqual({ kind: 'not_asked', result: body });
  });

  /* Status is not the signal: the service's own fault is a 503 WITH a decline body, and a
   * busy refusal is a 429 with one. Both are real responses a CSM should see. */
  it('trusts a contract body on a non-OK status', async () => {
    const busy = decline('service_busy');
    stubFetch(async () => reply(busy, 429, RECORDED));
    expect(await api.ask('q', null)).toMatchObject({ kind: 'answered', result: busy, recorded: true });
  });

  it.each([
    ['the proxy does not answer', async () => {
      throw new TypeError('network down');
    }],
    ['the body is not JSON', async () => reply('<html>502</html>', 502)],
    ['the body is JSON but not the contract', async () => reply({ outcome: 'something_else' })],
    ['the body is JSON null', async () => reply('null')],
    ['a 404 that is not the thread', async () => reply({ error: 'nope' }, 404)],
  ])('is the unreachable decline when %s', async (_label, impl) => {
    stubFetch(impl as () => Promise<Response>);
    expect(await api.ask('q', null)).toEqual({ kind: 'not_asked', result: api.UNREACHABLE });
  });
});
