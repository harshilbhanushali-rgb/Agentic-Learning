import { afterEach, describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { AskNarenResponse } from '@/types';
import type { StoredThreadJson, ThreadSummaryJson } from '@/lib/thread';

import { answer, clarify, decline, maximal } from '../../../tests/fixtures/ask-naren';
import { AskNaren } from './AskNaren';

/* The sign-out form's server action is not reachable from jsdom and is not what this file
 * is about; SignOutButton has its own test. */
vi.mock('@/app/login/actions', () => ({ signOut: vi.fn(), signIn: vi.fn() }));

const USER = { id: 7, name: 'Asha Rao' };
const DRAFT_KEY = 'cs-ask-naren-draft';

/* -- A fake of the same-origin routes -----------------------------------------------------
 * One handler per route, replaced per test. The page talks to nothing else, so a request to
 * anything outside this table is a test failure rather than a silent network call. */

function reply(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers });
}

const recorded = (thread: number, position: number) => ({
  'X-Ask-Naren-Thread': String(thread),
  'X-Ask-Naren-Position': String(position),
});

type Handler = (id: number, body: unknown) => Response | Promise<Response>;

let routes: { ask: Handler; list: Handler; get: Handler; patch: Handler; del: Handler };
let fetchMock: ReturnType<typeof vi.fn>;
let assign: ReturnType<typeof vi.fn>;

function summary(over: Partial<ThreadSummaryJson> = {}): ThreadSummaryJson {
  const at = new Date(Date.now() - 5 * 60_000).toISOString();
  return { id: 9, title: 'Applies are flat', renamed: false, createdAt: at, lastTurnAt: at, turnCount: 1, ...over };
}

function stored(id: number, turns: { question: string; response: AskNarenResponse }[]): StoredThreadJson {
  const at = new Date(Date.now() - 90 * 60_000).toISOString();
  return {
    ...summary({ id, turnCount: turns.length }),
    turns: turns.map((t, i) => ({ position: i + 1, ...t, askedAt: at, answeredAt: at })),
  };
}

/* Relative times ("1 hour ago", Today/Yesterday) are calendar-aware, so the clock is pinned
 * to local noon: nothing here may depend on when the suite happens to run. Only `Date` is
 * faked -- userEvent's own timers stay real. */
afterEach(() => {
  vi.useRealTimers();
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(2026, 8, 28, 12, 0, 0));
  sessionStorage.clear();
  routes = {
    ask: () => reply(answer(), 200, recorded(9, 1)),
    list: () => reply({ threads: [] }),
    get: id => reply({ thread: stored(id, []) }),
    patch: (id, body) => reply({ thread: summary({ id, title: String((body as { title: string }).title), renamed: true }) }),
    del: () => reply({ ok: true }),
  };
  fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const body = init.body ? JSON.parse(init.body as string) : undefined;
    const m = /^\/api\/ask-naren\/threads\/(\d+)$/.exec(url);
    if (url === '/api/ask-naren' && init.method === 'POST') return routes.ask(0, body);
    if (url === '/api/ask-naren/threads' && !init.method) return routes.list(0, body);
    if (m && !init.method) return routes.get(Number(m[1]), body);
    if (m && init.method === 'PATCH') return routes.patch(Number(m[1]), body);
    if (m && init.method === 'DELETE') return routes.del(Number(m[1]), body);
    throw new Error(`unexpected request: ${init.method ?? 'GET'} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  assign = vi.fn();
  vi.stubGlobal('location', { ...window.location, assign });
});

function calls(pred: (url: string, init: RequestInit) => boolean) {
  return fetchMock.mock.calls.filter(([url, init]) => pred(url as string, (init ?? {}) as RequestInit));
}
const askBodies = () =>
  calls((u, i) => u === '/api/ask-naren' && i.method === 'POST').map(([, i]) => JSON.parse((i as RequestInit).body as string));
const listCalls = () => calls((u, i) => u === '/api/ask-naren/threads' && !i.method).length;

function renderPage(initialThreads: ThreadSummaryJson[] = []) {
  return render(<AskNaren user={USER} initialThreads={initialThreads} />);
}

async function ask(user: ReturnType<typeof userEvent.setup>, text = 'applies are flat') {
  await user.type(screen.getByLabelText('The situation'), text);
  await user.click(screen.getByRole('button', { name: 'Ask Naren' }));
}

/** A promise the test resolves when it chooses, for holding a request in flight. */
function deferred<T>() {
  let resolve: (v: T) => void = () => {};
  const promise = new Promise<T>(r => (resolve = r));
  return { promise, resolve };
}

const rail = () => screen.getByRole('complementary', { name: 'Your threads' });

describe('AskNaren outcomes', () => {
  it('renders an answered response as the answer card', async () => {
    const user = userEvent.setup();
    renderPage();
    await ask(user);
    expect(await screen.findByText('What Naren actually said')).toBeInTheDocument();
    expect(screen.getByText('You asked')).toBeInTheDocument();
  });

  it('renders a declined response as the decline notice', async () => {
    const user = userEvent.setup();
    routes.ask = () => reply(decline('no_close_match'), 200, recorded(9, 1));
    renderPage();
    await ask(user);
    expect(await screen.findByText('No grounded answer')).toBeInTheDocument();
  });

  it('renders a clarify response as the question prompt', async () => {
    const user = userEvent.setup();
    routes.ask = () => reply(clarify(), 200, recorded(9, 1));
    renderPage();
    await ask(user);
    expect(await screen.findByText('One thing first')).toBeInTheDocument();
  });

  it('renders a rendered response through RenderedAnswer', async () => {
    const user = userEvent.setup();
    routes.ask = () => reply(maximal.show_exchange, 200, recorded(9, 1));
    renderPage();
    await ask(user);
    expect(await screen.findByText('The real exchange')).toBeInTheDocument();
  });

  /* A non-OK status still carries the contract -- a busy refusal is a 429 with a decline
   * body. Status is not the signal, and treating it as one would turn a real decline into a
   * synthesised one. */
  it('trusts the body, not the status code', async () => {
    const user = userEvent.setup();
    routes.ask = () => reply(decline('service_busy'), 429, recorded(9, 1));
    renderPage();
    await ask(user);
    expect(await screen.findByText('Ask Naren is busy')).toBeInTheDocument();
  });
});

describe('AskNaren: the thread is the server’s', () => {
  it('sends the situation and no thread on a first question, then the thread id it went into', async () => {
    const user = userEvent.setup();
    renderPage();

    await ask(user, 'client says applies are flat');
    await screen.findByText('What Naren actually said');
    await ask(user, 'and what if they push back?');
    await waitFor(() => expect(screen.getAllByText('You asked')).toHaveLength(2));

    // The browser never sends the thread itself: the route rebuilds it from storage.
    expect(askBodies()).toEqual([
      { situation: 'client says applies are flat', thread_id: null },
      { situation: 'and what if they push back?', thread_id: 9 },
    ]);
  });

  it('refreshes the rail after every answer', async () => {
    const user = userEvent.setup();
    routes.list = () => reply({ threads: [summary({ title: 'client says applies are flat' })] });
    renderPage();

    await ask(user, 'client says applies are flat');
    expect(await within(rail()).findByText('client says applies are flat')).toBeInTheDocument();
    expect(listCalls()).toBe(1);
  });

  /* #39: a stale carried scenario is the known wrong-answer risk, so the scenario the NEXT
   * question inherits is on screen, with the way out beside it. */
  it('names the scenario a follow-up would carry, and Start a new thread clears it', async () => {
    const user = userEvent.setup();
    renderPage();

    await ask(user);
    const banner = (await screen.findByText(/Continuing:/)).closest('p')!;
    expect(banner).toHaveTextContent('Continuing: performance pushback, last asked just now.');

    await user.click(within(banner).getByRole('button', { name: 'Start a new thread' }));
    expect(screen.queryByText(/Continuing/)).not.toBeInTheDocument();
    expect(screen.queryByText('You asked')).not.toBeInTheDocument();

    await ask(user, 'a different client');
    await screen.findByText('What Naren actually said');
    expect(askBodies()[1]).toEqual({ situation: 'a different client', thread_id: null });
  });

  it('says "Continuing this thread" when nothing in it carries a scenario', async () => {
    const user = userEvent.setup();
    routes.ask = () => reply(decline('no_close_match'), 200, recorded(9, 1));
    renderPage();

    await ask(user);
    expect(await screen.findByText(/Continuing this thread/)).toBeInTheDocument();
  });

  /* #40: a real answer the store failed to record is shown, flagged, and the next question
   * starts fresh rather than replaying a thread with a gap in it. */
  it('shows an unrecorded answer as not saved, and detaches the next question', async () => {
    const user = userEvent.setup();
    routes.ask = () => reply(answer(), 200, { ...recorded(9, 1), 'X-Ask-Naren-Recorded': 'false' });
    renderPage();

    await ask(user, 'first');
    expect(await screen.findByText('Not saved to this thread.')).toBeInTheDocument();
    expect(screen.getByText(/your next question starts a new thread\./)).toBeInTheDocument();
    expect(screen.queryByText(/Continuing/)).not.toBeInTheDocument();

    routes.ask = () => reply(answer({ answer: 'second answer' }), 200, recorded(11, 1));
    await ask(user, 'second');
    expect(await screen.findByText('second answer')).toBeInTheDocument();
    // The unsaved turn is gone from the screen with the thread it was never part of.
    expect(screen.queryByText('Not saved to this thread.')).not.toBeInTheDocument();
    expect(screen.getAllByText('You asked')).toHaveLength(1);
    expect(askBodies()[1]).toEqual({ situation: 'second', thread_id: null });
  });

  it('puts the question back when the open thread was removed elsewhere', async () => {
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'first');
    await screen.findByText('What Naren actually said');

    routes.ask = () => reply({ error: 'thread_not_found' }, 404);
    await ask(user, 'follow up');

    expect(await screen.findByRole('status')).toHaveTextContent(
      'That thread was removed from your list, so nothing was asked.',
    );
    expect(screen.getByLabelText('The situation')).toHaveValue('follow up');
    expect(screen.queryByText('You asked')).not.toBeInTheDocument();
  });

  /* The most valuable test on this page. A request takes seconds and "New thread" is
   * reachable throughout; without the generation guard the resolving `ask` would paint its
   * answer into the thread the CSM has since left. */
  it('drops an in-flight answer when the CSM starts a fresh thread, and refreshes the rail', async () => {
    const user = userEvent.setup();
    const late = deferred<Response>();
    routes.ask = () => late.promise;
    renderPage();

    await ask(user, 'second situation');
    expect(await screen.findByText(/Searching Naren’s calls/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /New thread/ }));
    expect(screen.queryByText(/Searching Naren’s calls/)).not.toBeInTheDocument();

    late.resolve(reply(answer({ answer: 'late answer' }), 200, recorded(9, 1)));
    // The turn WAS recorded in the thread it was asked in, so the rail learns about it.
    await waitFor(() => expect(listCalls()).toBe(1));
    expect(screen.queryByText('late answer')).not.toBeInTheDocument();
    expect(screen.queryByText('second situation')).not.toBeInTheDocument();
  });

  it('marks the region busy while a question is in flight, and ignores a second submit', async () => {
    const user = userEvent.setup();
    routes.ask = () => new Promise(() => {});
    renderPage();

    await ask(user);
    const live = document.querySelector('[aria-live="polite"]');
    expect(live).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByLabelText('The situation')).toBeDisabled();
    expect(askBodies()).toHaveLength(1);
  });
});

describe('AskNaren failures that are not turns', () => {
  it('shows an unreachable decline when the proxy itself does not answer, and keeps the question', async () => {
    const user = userEvent.setup();
    routes.ask = () => {
      throw new TypeError('network down');
    };
    renderPage();

    await ask(user, 'applies are flat');
    expect(await screen.findByText('Ask Naren is unavailable')).toBeInTheDocument();
    expect(screen.getByText(/Nothing was answered/)).toBeInTheDocument();
    expect(screen.getByLabelText('The situation')).toHaveValue('applies are flat');
    expect(screen.queryByText('You asked')).not.toBeInTheDocument();
  });

  it('shows the same decline when the body parses but is not the contract', async () => {
    const user = userEvent.setup();
    routes.ask = () => reply({ outcome: 'something_else', answer: 'hi' });
    renderPage();
    await ask(user);
    expect(await screen.findByText('Ask Naren is unavailable')).toBeInTheDocument();
  });

  it('shows a store fault once, above the thread, and asks nothing', async () => {
    const user = userEvent.setup();
    routes.ask = () => reply(decline('store_unavailable'), 500);
    renderPage();

    await ask(user, 'applies are flat');
    expect(await screen.findByText('Ask Naren can’t reach your threads')).toBeInTheDocument();
    expect(screen.getByLabelText('The situation')).toHaveValue('applies are flat');
    expect(screen.queryByText('You asked')).not.toBeInTheDocument();
    expect(listCalls()).toBe(0);
  });

  it('keeps the draft and the thread through a sign-in when the session ends mid-question', async () => {
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'first');
    await screen.findByText('What Naren actually said');

    routes.ask = () => reply({ error: 'signed_out' }, 401);
    await ask(user, 'the unsent follow-up');

    await waitFor(() => expect(assign).toHaveBeenCalledWith('/login?next=%2Fask-naren'));
    expect(JSON.parse(sessionStorage.getItem(DRAFT_KEY)!)).toEqual({
      userId: 7,
      draft: 'the unsent follow-up',
      threadId: 9,
    });
  });
});

describe('AskNaren rail', () => {
  it('lands a user with no threads on an empty box and the coverage guide', () => {
    renderPage();
    expect(screen.getByText('Where Naren’s calls go deepest')).toBeInTheDocument();
    expect(within(rail()).getByText(/No threads yet/)).toBeInTheDocument();
    expect(screen.getByText('Signed in as Asha Rao')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('lists a returning user’s threads and opens none of them', async () => {
    renderPage([summary()]);
    expect(await within(rail()).findByText('Applies are flat')).toBeInTheDocument();
    expect(screen.queryByText('Where Naren’s calls go deepest')).not.toBeInTheDocument();
    expect(calls(u => u.startsWith('/api/ask-naren/threads/'))).toHaveLength(0);
  });

  it('opens a thread from the rail with every stored turn through the same cards', async () => {
    const user = userEvent.setup();
    const held = deferred<Response>();
    routes.get = () => held.promise;
    renderPage([summary()]);

    await user.click(await within(rail()).findByRole('button', { name: /^Applies are flat/ }));
    expect(screen.getByText('Opening thread…')).toBeInTheDocument();

    held.resolve(
      reply({
        thread: stored(9, [
          { question: 'first question', response: answer() },
          { question: 'second question', response: decline('out_of_scope') },
        ]),
      }),
    );
    expect(await screen.findByText('first question')).toBeInTheDocument();
    expect(screen.getByText('second question')).toBeInTheDocument();
    expect(screen.getByText('What Naren actually said')).toBeInTheDocument();
    expect(screen.getByText('Outside what Naren’s calls cover')).toBeInTheDocument();
    // The carried scenario comes from the answered turn, past the later decline.
    expect(screen.getByText(/Continuing:/).closest('p')).toHaveTextContent(
      'Continuing: performance pushback, last asked 1 hour ago.',
    );
    expect(within(rail()).getByRole('button', { name: /^Applies are flat/ })).toHaveAttribute('aria-current', 'true');

    await ask(user, 'follow up');
    await waitFor(() => expect(askBodies()).toEqual([{ situation: 'follow up', thread_id: 9 }]));
  });

  it('says so when a thread from the rail was removed elsewhere, and refreshes the list', async () => {
    const user = userEvent.setup();
    routes.get = () => reply({ error: 'not_found' }, 404);
    renderPage([summary()]);

    await user.click(await within(rail()).findByRole('button', { name: /^Applies are flat/ }));
    expect(await screen.findByRole('status')).toHaveTextContent('That thread was removed from your list');
    await waitFor(() => expect(listCalls()).toBe(1));
    expect(within(rail()).getByText(/No threads yet/)).toBeInTheDocument();
  });

  it('says it is our fault when a thread will not open', async () => {
    const user = userEvent.setup();
    routes.get = () => reply({ error: 'store_unavailable' }, 500);
    renderPage([summary()]);

    await user.click(await within(rail()).findByRole('button', { name: /^Applies are flat/ }));
    expect(await screen.findByRole('status')).toHaveTextContent('so that thread did not open');
  });

  it('sends a signed-out user to sign in, remembering the thread they tried to open', async () => {
    const user = userEvent.setup();
    routes.get = () => reply({}, 401);
    renderPage([summary()]);

    await user.type(screen.getByLabelText('The situation'), 'half typed');
    await user.click(await within(rail()).findByRole('button', { name: /^Applies are flat/ }));
    await waitFor(() => expect(assign).toHaveBeenCalled());
    expect(JSON.parse(sessionStorage.getItem(DRAFT_KEY)!)).toEqual({ userId: 7, draft: 'half typed', threadId: 9 });
  });

  it('ignores a thread that finishes opening after the CSM moved on', async () => {
    const user = userEvent.setup();
    const held = deferred<Response>();
    routes.get = () => held.promise;
    renderPage([summary()]);

    await user.click(await within(rail()).findByRole('button', { name: /^Applies are flat/ }));
    await user.click(screen.getByRole('button', { name: /New thread/ }));
    held.resolve(reply({ thread: stored(9, [{ question: 'stale question', response: answer() }]) }));

    await waitFor(() => expect(screen.queryByText('Opening thread…')).not.toBeInTheDocument());
    expect(screen.queryByText('stale question')).not.toBeInTheDocument();
  });

  it('flags a rail it could not refresh as possibly out of date', async () => {
    const user = userEvent.setup();
    routes.list = () => reply({ error: 'store_unavailable' }, 500);
    renderPage();

    await ask(user);
    expect(await within(rail()).findByText(/may be out of date/)).toBeInTheDocument();
  });

  it('does not flag the rail when the refresh found the session ended', async () => {
    const user = userEvent.setup();
    routes.list = () => reply({}, 401);
    renderPage();

    await ask(user);
    await waitFor(() => expect(listCalls()).toBe(1));
    expect(within(rail()).queryByText(/may be out of date/)).not.toBeInTheDocument();
  });
});

describe('AskNaren rename and remove', () => {
  async function rename(user: ReturnType<typeof userEvent.setup>, title: string) {
    await user.click(await within(rail()).findByRole('button', { name: 'Rename “Applies are flat”' }));
    const field = screen.getByLabelText('Thread title');
    await user.clear(field);
    await user.type(field, `${title}{Enter}`);
  }

  it('renames in place', async () => {
    const user = userEvent.setup();
    renderPage([summary()]);
    await rename(user, 'Acme pause');
    expect(await within(rail()).findByText('Acme pause')).toBeInTheDocument();
    const [, init] = calls((u, i) => i.method === 'PATCH')[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ title: 'Acme pause' });
  });

  it('keeps the stored title and says why when the store is down', async () => {
    const user = userEvent.setup();
    routes.patch = () => reply({}, 500);
    renderPage([summary()]);
    await rename(user, 'Acme pause');
    expect(await screen.findByRole('status')).toHaveTextContent('Could not rename that thread');
    expect(within(rail()).getByText('Applies are flat')).toBeInTheDocument();
  });

  it('says a renamed thread was removed elsewhere, and refreshes the list without it', async () => {
    const user = userEvent.setup();
    routes.patch = () => reply({}, 404);
    renderPage([summary()]);
    await rename(user, 'Acme pause');
    expect(await screen.findByRole('status')).toHaveTextContent('That thread was removed from your list.');
    await waitFor(() => expect(listCalls()).toBe(1));
    expect(await within(rail()).findByText(/No threads yet/)).toBeInTheDocument();
  });

  it('signs in again when a rename finds the session ended', async () => {
    const user = userEvent.setup();
    routes.patch = () => reply({}, 401);
    renderPage([summary()]);
    await rename(user, 'Acme pause');
    await waitFor(() => expect(assign).toHaveBeenCalled());
  });

  async function remove(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await within(rail()).findByRole('button', { name: 'Remove “Applies are flat” from your list' }));
    await user.click(screen.getByRole('button', { name: 'Remove from your list' }));
  }

  it('removing the open thread leaves the list and empties the page', async () => {
    const user = userEvent.setup();
    routes.get = () => reply({ thread: stored(9, [{ question: 'first question', response: answer() }]) });
    renderPage([summary(), summary({ id: 10, title: 'Another' })]);

    await user.click(await within(rail()).findByRole('button', { name: /^Applies are flat/ }));
    await screen.findByText('first question');
    await remove(user);

    await waitFor(() => expect(within(rail()).queryByText('Applies are flat')).not.toBeInTheDocument());
    expect(within(rail()).getByText('Another')).toBeInTheDocument();
    expect(screen.queryByText('first question')).not.toBeInTheDocument();
  });

  it('treats a thread already gone as removed', async () => {
    const user = userEvent.setup();
    routes.del = () => reply({}, 404);
    renderPage([summary(), summary({ id: 10, title: 'Another' })]);
    await remove(user);
    await waitFor(() => expect(within(rail()).queryByText('Applies are flat')).not.toBeInTheDocument());
  });

  it('keeps the thread and says why when the store is down', async () => {
    const user = userEvent.setup();
    routes.del = () => reply({}, 500);
    renderPage([summary()]);
    await remove(user);
    expect(await screen.findByRole('status')).toHaveTextContent('Could not remove that thread');
    expect(within(rail()).getByText('Applies are flat')).toBeInTheDocument();
  });

  it('signs in again when a remove finds the session ended', async () => {
    const user = userEvent.setup();
    routes.del = () => reply({}, 401);
    renderPage([summary()]);
    await remove(user);
    await waitFor(() => expect(assign).toHaveBeenCalled());
  });
});

describe('AskNaren back from a sign-in it sent someone to', () => {
  it('restores the draft and reopens the thread it was going into', async () => {
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ userId: 7, draft: 'the unsent follow-up', threadId: 9 }));
    routes.get = () => reply({ thread: stored(9, [{ question: 'first question', response: answer() }]) });
    renderPage([summary()]);

    expect(await screen.findByText('first question')).toBeInTheDocument();
    expect(screen.getByLabelText('The situation')).toHaveValue('the unsent follow-up');
  });

  it('restores a draft with no thread to an empty box', async () => {
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ userId: 7, draft: '', threadId: null }));
    renderPage();
    expect(screen.getByLabelText('The situation')).toHaveValue('');
    expect(calls(u => u.startsWith('/api/ask-naren/threads/'))).toHaveLength(0);
  });
});

describe('AskNaren chat layout', () => {
  it('puts the question box under the conversation, newest answer just above it', async () => {
    const user = userEvent.setup();
    renderPage();
    await ask(user);
    const answer = await screen.findByText('What Naren actually said');
    const box = screen.getByLabelText('The situation');
    expect(answer.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe('AskNaren /help', () => {
  it('shows what Ask Naren can do, and sends nothing to the service', async () => {
    const user = userEvent.setup();
    renderPage();
    await ask(user, '/help');
    expect(await screen.findByRole('region', { name: 'What Ask Naren can do' })).toBeInTheDocument();
    expect(askBodies()).toEqual([]);
    expect(screen.getByLabelText('The situation')).toHaveValue('');
  });

  it('is not a turn: the thread is untouched and the next question continues it', async () => {
    const user = userEvent.setup();
    renderPage();
    await ask(user, 'applies are flat');
    await screen.findByText('What Naren actually said');
    await ask(user, '/help');
    await screen.findByRole('region', { name: 'What Ask Naren can do' });
    expect(screen.getAllByText('You asked')).toHaveLength(1);
    routes.ask = () => reply(answer(), 200, recorded(9, 2));
    await ask(user, 'and if they push back');
    await waitFor(() => expect(askBodies()).toHaveLength(2));
    expect(askBodies()[1].thread_id).toBe(9);
  });

  it('closes', async () => {
    const user = userEvent.setup();
    renderPage();
    await ask(user, '/help');
    await user.click(await screen.findByRole('button', { name: 'Close help' }));
    expect(screen.queryByRole('region', { name: 'What Ask Naren can do' })).not.toBeInTheDocument();
  });

  it('ignores case and surrounding spaces, but a question that starts with "help" is a question', async () => {
    const user = userEvent.setup();
    renderPage();
    await ask(user, '  /HELP ');
    expect(await screen.findByRole('region', { name: 'What Ask Naren can do' })).toBeInTheDocument();
    await ask(user, 'help, the client says applies are flat');
    await waitFor(() => expect(askBodies()).toHaveLength(1));
  });

  it('says it exists, next to the box', () => {
    renderPage();
    expect(screen.getByText(/\/help/)).toBeInTheDocument();
  });
});
