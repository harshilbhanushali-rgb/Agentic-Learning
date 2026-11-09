'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * Copies an answer to the clipboard, so it can go straight into a reply to the client.
 *
 * Says what happened, including when it did not: the clipboard API is missing on an insecure
 * origin and can be refused by the browser, and a button that silently does nothing would
 * leave a CSM pasting whatever was on their clipboard before.
 */
export function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const copy = async () => {
    let ok = false;
    try {
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(text);
        ok = true;
      }
    } catch {
      ok = false;
    }
    setState(ok ? 'copied' : 'failed');
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState('idle'), 2500);
  };

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={copy}
        className="inline-flex h-10 items-center gap-1.5 rounded-md px-2.5 text-[14px] font-semibold text-ink-2 transition-colors duration-fast ease-out-quart hover:bg-surface-raised hover:text-ink"
      >
        {state === 'copied' ? (
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
        ) : (
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h9" /></svg>
        )}
        {state === 'copied' ? 'Copied' : 'Copy'}
      </button>
      <span role="status" className="text-[13px] text-ink-2">
        {state === 'copied' ? <span className="sr-only">Answer copied</span> : null}
        {state === 'failed' ? 'Could not copy here. Select the text and copy it instead.' : null}
      </span>
    </div>
  );
}
