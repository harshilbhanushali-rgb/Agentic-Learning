import { beforeEach, describe, it, expect, vi } from 'vitest';

import { clearStash, stashAndSignIn, takeStash } from './draftStash';

const KEY = 'cs-ask-naren-draft';

// tests/setup.ts resets localStorage only; the stash lives in sessionStorage.
beforeEach(() => sessionStorage.clear());

/** jsdom cannot navigate; `location` is configurable on its window, so stub the whole of it. */
function stubLocation() {
  const assign = vi.fn();
  vi.stubGlobal('location', { ...window.location, assign });
  return assign;
}

describe('stashAndSignIn', () => {
  it('keeps the draft and thread for this user, then goes to sign in and back', () => {
    const assign = stubLocation();
    stashAndSignIn(7, { draft: 'half a question', threadId: 12 });

    expect(JSON.parse(sessionStorage.getItem(KEY)!)).toEqual({
      userId: 7,
      draft: 'half a question',
      threadId: 12,
    });
    expect(assign).toHaveBeenCalledWith('/login?next=%2Fask-naren');
  });

  it('still signs in when storage is unavailable', () => {
    const assign = stubLocation();
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError');
    });
    expect(() => stashAndSignIn(7, { draft: 'd', threadId: null })).not.toThrow();
    expect(assign).toHaveBeenCalled();
  });
});

describe('takeStash', () => {
  function put(value: unknown) {
    sessionStorage.setItem(KEY, typeof value === 'string' ? value : JSON.stringify(value));
  }

  it('is null when nothing was stashed -- a normal sign-in lands on an empty box', () => {
    expect(takeStash(7)).toBeNull();
  });

  it('returns the stash once, removing it', () => {
    put({ userId: 7, draft: 'd', threadId: 12 });
    expect(takeStash(7)).toEqual({ draft: 'd', threadId: 12 });
    expect(sessionStorage.getItem(KEY)).toBeNull();
    expect(takeStash(7)).toBeNull();
  });

  it('gives a different user nothing, and still removes it', () => {
    put({ userId: 7, draft: 'd', threadId: 12 });
    expect(takeStash(8)).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it.each([
    ['a non-string draft', { userId: 7, draft: 5, threadId: 3 }, { draft: '', threadId: 3 }],
    ['a string thread id', { userId: 7, draft: 'd', threadId: '3' }, { draft: 'd', threadId: null }],
    ['a zero thread id', { userId: 7, draft: 'd', threadId: 0 }, { draft: 'd', threadId: null }],
    ['a fractional thread id', { userId: 7, draft: 'd', threadId: 1.5 }, { draft: 'd', threadId: null }],
    ['no thread id', { userId: 7, draft: 'd' }, { draft: 'd', threadId: null }],
  ])('sanitises %s', (_label, stored, expected) => {
    put(stored);
    expect(takeStash(7)).toEqual(expected);
  });

  it('is null for unparseable JSON rather than throwing', () => {
    put('{not json');
    expect(takeStash(7)).toBeNull();
  });
});

describe('clearStash', () => {
  it('removes the draft', () => {
    sessionStorage.setItem(KEY, '{}');
    clearStash();
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it('swallows a storage failure', () => {
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('SecurityError');
    });
    expect(() => clearStash()).not.toThrow();
  });
});
