'use client';

/**
 * PROTOTYPE-ONLY floating switcher. Deliberately styled unlike the product (dark pill, raw
 * colours) so nobody mistakes it for part of a design. Hidden in production builds.
 *
 * Cycles `?variant=` with the arrows (and ← / → keys when no field is focused), and toggles any
 * extra URL params listed in `toggles`.
 */
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect } from 'react';

export interface Toggle {
  param: string;
  label: string;
  options: string[];
}

export function PrototypeSwitcher({
  variants,
  toggles = [],
}: {
  variants: { key: string; name: string }[];
  toggles?: Toggle[];
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const current = params.get('variant') ?? variants[0].key;
  const idx = Math.max(0, variants.findIndex(v => v.key === current));

  const set = useCallback(
    (param: string, value: string) => {
      const next = new URLSearchParams(params.toString());
      next.set(param, value);
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    },
    [params, pathname, router],
  );

  const step = useCallback(
    (d: number) => set('variant', variants[(idx + d + variants.length) % variants.length].key),
    [idx, set, variants],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
      if (e.key === 'ArrowLeft') step(-1);
      if (e.key === 'ArrowRight') step(1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [step]);

  if (process.env.NODE_ENV === 'production') return null;

  const btn = 'rounded-full px-2 py-1 hover:bg-white/15';
  return (
    <div
      className="fixed bottom-4 left-1/2 z-[1000] flex -translate-x-1/2 flex-wrap items-center gap-3 rounded-full px-4 py-2 text-[12px] shadow-lg"
      style={{ background: '#111', color: '#f5f5f5', fontFamily: 'ui-monospace, monospace' }}
    >
      <span style={{ color: '#f59e0b' }}>PROTOTYPE</span>
      <button type="button" className={btn} onClick={() => step(-1)} aria-label="Previous variant">‹</button>
      <span>
        {variants[idx].key} ({variants[idx].name})
      </span>
      <button type="button" className={btn} onClick={() => step(1)} aria-label="Next variant">›</button>
      {toggles.map(t => {
        const value = params.get(t.param) ?? t.options[0];
        return (
          <span key={t.param} className="flex items-center gap-1 border-l border-white/20 pl-3">
            <span style={{ color: '#9ca3af' }}>{t.label}</span>
            {t.options.map(o => (
              <button
                key={o}
                type="button"
                onClick={() => set(t.param, o)}
                className="rounded-full px-2 py-0.5"
                style={o === value ? { background: '#f5f5f5', color: '#111' } : undefined}
              >
                {o}
              </button>
            ))}
          </span>
        );
      })}
    </div>
  );
}
