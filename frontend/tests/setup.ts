import '@testing-library/jest-dom/vitest';
import { afterEach, beforeEach, vi } from 'vitest';

/* ---------------------------------------------------------------------------
 * jsdom gaps this app walks into. Both are hard crashes, not degradations.
 *
 * ALL OF IT IS GUARDED ON THERE BEING A DOM AT ALL. setupFiles runs for EVERY test file,
 * including the ones that opt into `// @vitest-environment node` to exercise the SSR
 * guards in src/lib/thread.ts. There is no `window` in those, so an unguarded
 * `Object.defineProperty(window, ...)` throws and fails the whole file before a single
 * test runs -- and vitest reports that as a file-level error, which is easy to miss in a
 * summarised run.
 * ------------------------------------------------------------------------- */
const hasDom = typeof window !== 'undefined';

if (hasDom) {
  /** RadarDeckStack consults `matchMedia('(prefers-reduced-motion: reduce)')` on every deck
   *  navigation. jsdom does not implement it at all, so the click throws before any
   *  assertion runs. Declared writable so a test can flip `matches` and drive both the
   *  immediate-swap and the deferred-swap branch. */
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });

  /** origin-button constructs one in a layout effect on hover/focus/pointerdown. Rendering
   *  is safe without it; interacting is not. Needed even though the component itself is
   *  coverage-excluded, because /simulator renders it.
   *
   *  Assigned directly rather than via `vi.stubGlobal`, because the `vi.unstubAllGlobals()`
   *  in afterEach below would tear a stubbed global back down after the FIRST test and
   *  leave every later one crashing. */
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

/* ---------------------------------------------------------------------------
 * Per-test isolation. Every persistence path in this app is localStorage, and the theme is
 * an attribute on <html> that AppShell mutates directly -- neither is reset by React
 * unmounting, so both leak across tests without this.
 * ------------------------------------------------------------------------- */
beforeEach(() => {
  if (!hasDom) return;
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
