// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { clearLegacyThreads } from './thread';

/**
 * The `typeof window === 'undefined'` guard in clearLegacyThreads() is unreachable under
 * jsdom -- there is always a window there -- so it would sit permanently uncovered and,
 * worse, permanently unexercised. This file runs the same module with no DOM at all, which
 * is what the server render actually does.
 */
describe('thread storage during SSR', () => {
  it('has no window to read', () => {
    expect(typeof window).toBe('undefined');
  });

  it('clearing legacy threads is a no-op rather than a crash', () => {
    expect(() => clearLegacyThreads()).not.toThrow();
  });
});
