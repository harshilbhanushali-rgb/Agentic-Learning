'use client';
import type { ReactNode } from 'react';
import type { Mode } from '@/types';

import { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  MenuIcon, SearchIcon, BellIcon, BellSmIcon, ChatIcon, SunIcon, MoonIcon, BookmarkIcon,
} from '@/components/icons';

const ORACLE_DATA = [
  { q: 'ROI benchmarks by industry',              cat: 'Benchmarks' },
  { q: 'Objection: "We have internal tools"',     cat: 'Objections' },
  { q: 'Account A · 18-month renewal arc',        cat: 'Accounts'   },
  { q: 'CPH to brand ROI reframe',                cat: 'Narratives' },
  { q: 'Sanofi onboarding status Q1 2025',        cat: 'Accounts'   },
  { q: 'QBR opening framework — skeptical CXO',   cat: 'Playbooks'  },
  { q: 'Project Atlas · what went wrong',         cat: 'Failures'   },
  { q: 'Competitive displacement · ATS market',   cat: 'Objections' },
  { q: 'FMCG renewal narrative best practices',   cat: 'Playbooks'  },
  { q: 'Account J · escalation timeline',         cat: 'Accounts'   },
];

const NAV_ITEMS = [
  { href: '/workspace', label: 'Workspace', shortcut: 'G W', key: 'w' },
  { href: '/library',   label: 'Library',   shortcut: 'G L', key: 'l' },
  { href: '/simulator', label: 'Simulator', shortcut: 'G S', key: 's' },
];

const MODE_LABEL: Record<Mode, string> = { veteran: 'Veteran', newbie: 'Newbie' };

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname  = usePathname();
  const router    = useRouter();
  const [mounted,      setMounted]      = useState(false);
  const [mode,         setMode]         = useState<Mode>('veteran');
  const [sidebarOpen,  setSidebarOpen]  = useState(true);
  const [darkMode,     setDarkMode]     = useState(false);
  const [oracleQuery,  setOracleQuery]  = useState('');
  const [oracleOpen,   setOracleOpen]   = useState(false);
  const [oracleActive, setOracleActive] = useState(-1);
  const [toast,        setToast]        = useState<string | null>(null);
  const oracleRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setMounted(true);
    const storedMode    = localStorage.getItem('cs-mode') || 'veteran';
    const storedSidebar = localStorage.getItem('cs-sidebar');
    const storedTheme   = localStorage.getItem('cs-theme');
    setMode(storedMode as Mode);
    if (storedSidebar === 'closed') setSidebarOpen(false);
    if (storedTheme === 'dark') {
      setDarkMode(true);
      document.documentElement.dataset.theme = 'dark';
    }
  }, []);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (oracleRef.current && !oracleRef.current.contains(e.target as Node)) {
        setOracleOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Auto-dismiss the mode-switch toast.
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 2600);
    return () => clearTimeout(id);
  }, [toast]);

  // Global keyboard shortcuts: ⌘K / Ctrl+K focuses the Oracle; "g" then w/l/s routes.
  useEffect(() => {
    let gPending = false;
    let gTimer: ReturnType<typeof setTimeout>;
    const isTyping = (target: EventTarget | null) => {
      const el = target as HTMLElement | null;
      return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);
    };
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOracleOpen(true);
        searchInputRef.current?.focus();
        return;
      }
      if (isTyping(e.target)) return;
      if (gPending) {
        const dest = NAV_ITEMS.find(n => n.key === e.key.toLowerCase());
        clearTimeout(gTimer);
        gPending = false;
        if (dest) { e.preventDefault(); router.push(dest.href); }
        return;
      }
      if (e.key.toLowerCase() === 'g' && !e.metaKey && !e.ctrlKey && !e.altKey) {
        gPending = true;
        gTimer = setTimeout(() => { gPending = false; }, 1200);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => { window.removeEventListener('keydown', onKey); clearTimeout(gTimer); };
  }, [router]);

  const oracleResults = oracleQuery.trim()
    ? ORACLE_DATA.filter(d => d.q.toLowerCase().includes(oracleQuery.toLowerCase()))
    : ORACLE_DATA.slice(0, 5);

  const selectOracle = (q: string) => {
    setOracleQuery(q);
    setOracleOpen(false);
    setOracleActive(-1);
  };

  const toggleTheme = () => {
    setDarkMode(d => {
      const next = !d;
      document.documentElement.dataset.theme = next ? 'dark' : '';
      localStorage.setItem('cs-theme', next ? 'dark' : 'light');
      return next;
    });
  };

  const switchMode = (m: Mode) => {
    if (m === mode) return;
    setMode(m);
    localStorage.setItem('cs-mode', m);
    window.dispatchEvent(new CustomEvent('cs-mode-change', { detail: m }));
    setToast(`Switched to ${MODE_LABEL[m]} view`);
  };

  const toggleSidebar = () => {
    setSidebarOpen(o => {
      localStorage.setItem('cs-sidebar', o ? 'closed' : 'open');
      return !o;
    });
  };

  return (
    <div className={`app-layout${sidebarOpen ? '' : ' sidebar-collapsed'}`}>

      {/* ── SIDEBAR ───────────────────────────────────── */}
      <aside className="app-sidebar" aria-label="Application sidebar">

        <div className="sidebar-org">
          <div className="sidebar-org-logo">CC</div>
          <div className="sidebar-org-text">
            <div className="sidebar-org-name">Customer Champi…</div>
            <div className="sidebar-org-ver">CS · V2.0</div>
          </div>
        </div>

        <nav className="sidebar-nav" aria-label="Pages">
          <div className="sidebar-section-label">Pages</div>
          {NAV_ITEMS.map(({ href, label, shortcut }) => {
            const active = pathname === href || pathname.startsWith(href + '/');
            return (
              <Link
                key={href}
                href={href}
                className={`sidebar-item${active ? ' is-active' : ''}`}
                aria-current={active ? 'page' : undefined}
                title={sidebarOpen ? undefined : label}
              >
                <span className="sidebar-item-dot" aria-hidden="true" />
                <span className="sidebar-item-label">{label}</span>
                <span className="sidebar-item-shortcut" aria-hidden="true">{shortcut}</span>
              </Link>
            );
          })}
        </nav>

        <div className="sidebar-today-section">
          <div className="sidebar-section-label">Today</div>
          <button className="sidebar-item" title={sidebarOpen ? undefined : 'Chatbot history'}>
            <ChatIcon />
            <span className="sidebar-item-label">Chatbot history</span>
          </button>
          <button className="sidebar-item" title={sidebarOpen ? undefined : 'Saved clips'}>
            <BookmarkIcon />
            <span className="sidebar-item-label">Saved clips</span>
          </button>
          <button className="sidebar-item" title={sidebarOpen ? undefined : 'Knowledge drops (3 new)'}>
            <BellSmIcon />
            <span className="sidebar-item-label">Knowledge drops</span>
            <span className="sidebar-badge">3</span>
          </button>
        </div>

        <div className="sidebar-spacer" />

        <div className="sidebar-user">
          <div className="sidebar-user-avatar">PS</div>
          <div className="sidebar-user-info">
            <div className="sidebar-user-name">Priya Sharma</div>
            <div className="sidebar-user-meta">VETERAN · APAC</div>
          </div>
        </div>

      </aside>

      {/* ── CONTENT ZONE ──────────────────────────────── */}
      <div className="app-content-zone">

        <header className="app-topbar">
          <button
            className="sidebar-toggle-btn"
            onClick={toggleSidebar}
            aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            aria-expanded={sidebarOpen}
          >
            <MenuIcon />
          </button>
          <div className="topbar-search" ref={oracleRef}>
            <SearchIcon />
            <input
              ref={searchInputRef}
              className="topbar-search-input"
              type="text"
              placeholder="Ask anything — ROI benchmarks, objection handles, client history…"
              role="combobox"
              aria-label="Knowledge Oracle"
              aria-expanded={oracleOpen}
              aria-haspopup="listbox"
              aria-autocomplete="list"
              aria-controls="oracle-listbox"
              aria-activedescendant={oracleOpen && oracleActive >= 0 ? `oracle-opt-${oracleActive}` : undefined}
              value={oracleQuery}
              onChange={e => { setOracleQuery(e.target.value); setOracleActive(-1); }}
              onFocus={() => setOracleOpen(true)}
              onKeyDown={e => {
                if (e.key === 'Escape') {
                  setOracleOpen(false); setOracleActive(-1); e.currentTarget.blur(); return;
                }
                if (e.key === 'ArrowDown') {
                  e.preventDefault(); setOracleOpen(true);
                  setOracleActive(i => Math.min(i + 1, oracleResults.length - 1)); return;
                }
                if (e.key === 'ArrowUp') {
                  e.preventDefault(); setOracleActive(i => Math.max(i - 1, -1)); return;
                }
                if (e.key === 'Enter' && oracleActive >= 0 && oracleResults[oracleActive]) {
                  e.preventDefault(); selectOracle(oracleResults[oracleActive].q);
                }
              }}
            />
            <div className="topbar-oracle-live">
              <span className="oracle-live-dot" aria-hidden="true" />
              <span className="oracle-live-label">Oracle live</span>
            </div>
            <kbd className="topbar-kbd">⌘K</kbd>
            {oracleOpen && (
              <div className="oracle-dropdown" id="oracle-listbox" role="listbox" aria-label="Oracle suggestions">
                <div className="oracle-dropdown-label">
                  {oracleQuery.trim() ? `Results for "${oracleQuery}"` : 'Suggested'}
                </div>
                {oracleResults.length === 0 ? (
                  <div className="oracle-empty">
                    <div className="oracle-empty-title">No results for &ldquo;{oracleQuery}&rdquo;</div>
                    <div className="oracle-empty-hint">Try: ROI benchmarks, objection handles, client history</div>
                  </div>
                ) : (
                  oracleResults.map((item, i) => {
                    const active = i === oracleActive;
                    return (
                      <button
                        key={i}
                        id={`oracle-opt-${i}`}
                        className={`oracle-result${active ? ' is-active' : ''}`}
                        role="option"
                        aria-selected={active}
                        onMouseEnter={() => setOracleActive(i)}
                        onMouseDown={e => { e.preventDefault(); selectOracle(item.q); }}
                      >
                        <span className="oracle-result-q">{item.q}</span>
                        <span className="oracle-result-cat">{item.cat}</span>
                      </button>
                    );
                  })
                )}
                {oracleQuery.trim() && oracleResults.length > 0 && (
                  <div className="oracle-dropdown-footer">
                    {oracleResults.length} result{oracleResults.length !== 1 ? 's' : ''} · powered by Oracle
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="topbar-controls">
            {mounted && (
              <div className="mode-switcher" role="group" aria-label="User experience mode">
                <button
                  className={`mode-btn${mode === 'veteran' ? ' is-active' : ''}`}
                  onClick={() => switchMode('veteran')}
                  aria-pressed={mode === 'veteran'}
                >Veteran</button>
                <button
                  className={`mode-btn${mode === 'newbie' ? ' is-active' : ''}`}
                  onClick={() => switchMode('newbie')}
                  aria-pressed={mode === 'newbie'}
                >Newbie</button>
              </div>
            )}
            {mounted && (
              <button
                className="topbar-notif-btn"
                onClick={toggleTheme}
                aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
                aria-pressed={darkMode}
              >
                {darkMode ? <SunIcon /> : <MoonIcon />}
              </button>
            )}
            <button className="topbar-notif-btn" aria-label="Notifications">
              <BellIcon />
            </button>
          </div>
        </header>

        <main className="app-main">
          {children}
        </main>

      </div>

      {/* Mode-switch confirmation — announced to screen readers, auto-dismisses */}
      <div className="cs-toast-region" role="status" aria-live="polite">
        {toast && <div className="cs-toast">{toast}</div>}
      </div>
    </div>
  );
}
