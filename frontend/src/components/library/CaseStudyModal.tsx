'use client';
import type { CaseStudy } from '@/types';

import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

export function CaseStudyModal({ cs, onClose }: { cs: CaseStudy; onClose: () => void }) {
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = modalRef.current;
    if (!el) return;

    const focusable = el.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    first?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.key !== 'Tab') return;
      if (e.shiftKey) {
        if (document.activeElement === first) { e.preventDefault(); last?.focus(); }
      } else {
        if (document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const written = cs.chapters.length;

  return createPortal(
    <div className="anim-backdrop fixed inset-0 z-modal-backdrop flex items-center justify-center p-6" style={{ background: 'oklch(0 0 0 / 0.48)' }} onClick={onClose}>
      <div
        className="anim-modal bg-bg border-[1.5px] border-line rounded-lg p-8 max-w-[600px] w-full max-h-[calc(100vh-var(--space-12))] overflow-y-auto shadow-ambient"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="cs-modal-title"
        ref={modalRef}
      >
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-full text-[11px] font-semibold leading-none whitespace-nowrap bg-surface-raised text-ink-2 border border-line">{cs.account}</span>
            <h2 className="text-xl font-bold text-ink mt-2 tracking-[-0.02em]" id="cs-modal-title">{cs.headline}</h2>
            <span className="block text-sm text-ink-2 mt-1">
              {cs.context} · {written} of {cs.total} chapters written
            </span>
          </div>
          <button className="w-8 h-8 border border-line rounded-sm flex items-center justify-center cursor-pointer text-ink-2 text-sm shrink-0 transition duration-fast ease-out-quart hover:text-ink hover:bg-surface" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="h-px bg-line-subtle mb-5" />
        <div className="flex flex-col gap-5">
          {cs.chapters.map(ch => (
            <div key={ch.num} className="flex gap-4 items-start">
              <span className="font-mono text-[10px] font-semibold text-ink-placeholder tracking-[0.06em] uppercase shrink-0 pt-0.5 min-w-[38px]">Ch {ch.num}</span>
              <div>
                <div className="text-sm font-semibold text-ink mb-1">{ch.title}</div>
                <div className="text-sm text-ink-2 leading-base">{ch.summary}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>,
    document.body
  );
}
