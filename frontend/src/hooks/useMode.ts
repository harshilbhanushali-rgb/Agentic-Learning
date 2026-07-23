'use client';

import { useState, useEffect } from 'react';
import type { Mode } from '@/types';

export function useMode(): Mode {
  const [mode, setMode] = useState<Mode>('veteran');
  useEffect(() => {
    setMode((localStorage.getItem('cs-mode') as Mode) || 'veteran');
    const handler = (e: Event) => setMode((e as CustomEvent<Mode>).detail);
    window.addEventListener('cs-mode-change', handler);
    return () => window.removeEventListener('cs-mode-change', handler);
  }, []);
  return mode;
}
