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

  /** Node 25+ ships its own experimental `localStorage` / `sessionStorage` globals. Without
   *  `--localstorage-file` they are `undefined`, and because vitest's jsdom environment will
   *  not overwrite a global that already exists, they SHADOW jsdom's working ones -- every
   *  `localStorage.clear()` then throws "Cannot read properties of undefined". Provide an
   *  in-memory Storage only when the real one is missing, so older Node is untouched.
   *
   *  Instances inherit from `Storage.prototype` and the methods are patched onto it (falling
   *  through to jsdom's originals for any other receiver), because tests spy on
   *  `Storage.prototype.removeItem` to simulate unavailable storage -- own methods on the
   *  instance would shadow that spy. */
  const stores = new WeakMap<object, Map<string, string>>();
  const proto = Storage.prototype as unknown as Record<string, (...args: unknown[]) => unknown>;
  let patched = false;
  const patchPrototype = () => {
    if (patched) return;
    patched = true;
    const original: Record<string, (...args: unknown[]) => unknown> = {};
    for (const method of ['clear', 'getItem', 'setItem', 'removeItem', 'key']) {
      original[method] = proto[method]!;
    }
    const lengthDescriptor = Object.getOwnPropertyDescriptor(Storage.prototype, 'length');
    const mine = (self: object) => stores.get(self);
    const wrap = (
      name: string,
      impl: (store: Map<string, string>, ...args: string[]) => unknown,
    ) => {
      proto[name] = function (this: object, ...args: unknown[]) {
        const store = mine(this);
        return store ? impl(store, ...(args as string[])) : original[name]?.apply(this, args);
      };
    };
    wrap('clear', (m) => m.clear());
    wrap('getItem', (m, k) => (m.has(String(k)) ? m.get(String(k)) : null));
    wrap('setItem', (m, k, v) => void m.set(String(k), String(v)));
    wrap('removeItem', (m, k) => void m.delete(String(k)));
    wrap('key', (m, i) => Array.from(m.keys())[Number(i)] ?? null);
    Object.defineProperty(Storage.prototype, 'length', {
      configurable: true,
      get(this: object) {
        const store = mine(this);
        return store ? store.size : (lengthDescriptor?.get?.call(this) as number);
      },
    });
  };

  for (const name of ['localStorage', 'sessionStorage'] as const) {
    let usable = false;
    try {
      usable = typeof globalThis[name]?.clear === 'function';
    } catch {
      usable = false;
    }
    if (usable) continue;
    patchPrototype();
    const memory = Object.create(Storage.prototype) as Storage;
    stores.set(memory, new Map());
    Object.defineProperty(globalThis, name, { value: memory, configurable: true, writable: true });
  }
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
