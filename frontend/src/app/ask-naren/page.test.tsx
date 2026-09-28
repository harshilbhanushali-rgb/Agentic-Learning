import { describe, it, expect, vi, beforeEach } from 'vitest';
import { isValidElement, type ReactElement } from 'react';

/* The server wrapper: the sign-in check and the rail's read happen here, before anything
 * renders. The client component it hands off to is tested in
 * src/components/ask-naren/AskNaren.test.tsx. */

const requireUser = vi.fn();
vi.mock('@/server/auth/current-user', () => ({ requireUser: (to: string) => requireUser(to) }));

const theDb = { query: vi.fn() };
vi.mock('@/server/db', () => ({ db: () => theDb }));

const listThreads = vi.fn();
vi.mock('@/server/threads', () => ({ listThreads: (...a: unknown[]) => listThreads(...a) }));

vi.mock('@/components/ask-naren/AskNaren', () => ({ AskNaren: () => null }));

const { default: AskNarenPage } = await import('./page');
const { AskNaren } = await import('@/components/ask-naren/AskNaren');

beforeEach(() => {
  requireUser.mockReset();
  listThreads.mockReset();
});

describe('AskNarenPage', () => {
  it('renders the page for the signed-in user with their rail as JSON', async () => {
    requireUser.mockResolvedValue({ id: 7, name: 'Asha Rao', email: 'asha@joveo.com' });
    const at = new Date('2026-09-01T10:00:00.000Z');
    listThreads.mockResolvedValue([{ id: 3, title: 't', renamed: false, createdAt: at, lastTurnAt: at, turnCount: 2 }]);

    const el = (await AskNarenPage()) as ReactElement;
    expect(isValidElement(el)).toBe(true);
    expect(el.type).toBe(AskNaren);
    // Only id and name cross to the client: the email is not needed there.
    expect(el.props).toEqual({
      user: { id: 7, name: 'Asha Rao' },
      initialThreads: [
        {
          id: 3,
          title: 't',
          renamed: false,
          createdAt: '2026-09-01T10:00:00.000Z',
          lastTurnAt: '2026-09-01T10:00:00.000Z',
          turnCount: 2,
        },
      ],
    });
    expect(requireUser).toHaveBeenCalledWith('/ask-naren');
    expect(listThreads).toHaveBeenCalledWith(theDb, 7);
  });

  it('reads nothing for someone who is not signed in', async () => {
    requireUser.mockRejectedValue(new Error('NEXT_REDIRECT /login?next=%2Fask-naren'));
    await expect(AskNarenPage()).rejects.toThrow('NEXT_REDIRECT');
    expect(listThreads).not.toHaveBeenCalled();
  });

  it('lets a store fault reach error.tsx rather than render an empty rail', async () => {
    requireUser.mockResolvedValue({ id: 7, name: 'A', email: 'a@joveo.com' });
    listThreads.mockRejectedValue(new Error('connection refused'));
    await expect(AskNarenPage()).rejects.toThrow('connection refused');
  });
});
