'use client';
import type { ReactNode } from 'react';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { MenuIcon, SunIcon, MoonIcon } from '@/components/icons';
import { SignOutButton } from '@/components/auth/SignOutButton';
import { N10Mark, PRODUCT_NAME } from '@/components/ask-naren/N10Mark';
import { SIDEBAR_SLOT_ID } from '@/components/sidebarSlot';

/**
 * The app shell while Ask Naren is the only live page.
 *
 * Workspace, Library and Simulator are archived under src/app/_archive/ -- a private folder,
 * so Next serves no route for them -- and the full shell that went with them (the Oracle
 * search, the Veteran/Newbie switch, notifications, the mock "Today" items and mock profile) is
 * kept at src/components/_archive/AppShell.tsx. None of that did anything real: bringing it
 * back is restoring those files, not rebuilding them.
 *
 * NO MODE SWITCH, DELIBERATELY. Ask Naren renders identically in both modes, so with it the
 * only page, a Veteran/Newbie toggle would be a control that changes nothing. The
 * `cs-mode` key and `useMode` stay for the archived pages.
 */
const HOME = '/ask-naren';

function initials(name: string): string {
  // Words that start with a letter or digit: "E2E Test (Claude)" is "ET", not "E(".
  const startsWord = (w: string) => /\d/.test(w[0]) || w[0].toLowerCase() !== w[0].toUpperCase();
  const parts = name.trim().split(/\s+/).filter(startsWord);
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase() || '?';
}

export default function AppShell({
  children,
  user,
}: {
  children: ReactNode;
  /** The signed-in user, resolved by the root layout; null when nobody is signed in. */
  user: { name: string; email: string; isAdmin?: boolean } | null;
}) {
  const [mounted, setMounted] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [darkMode, setDarkMode] = useState(false);

  useEffect(() => {
    setMounted(true);
    if (localStorage.getItem('n10-sidebar') === 'closed') setSidebarOpen(false);
    if (localStorage.getItem('cs-theme') === 'dark') {
      setDarkMode(true);
      document.documentElement.dataset.theme = 'dark';
    }
  }, []);

  const toggleTheme = () => {
    setDarkMode(d => {
      const next = !d;
      document.documentElement.dataset.theme = next ? 'dark' : '';
      localStorage.setItem('cs-theme', next ? 'dark' : 'light');
      return next;
    });
  };

  const toggleSidebar = () => {
    setSidebarOpen(o => {
      localStorage.setItem('n10-sidebar', o ? 'closed' : 'open');
      return !o;
    });
  };

  return (
    <div className={`app-layout${sidebarOpen ? '' : ' sidebar-collapsed'}`}>
      <aside className="app-sidebar" aria-label="Application sidebar">
        <Link href={HOME} className="sidebar-org" aria-label={`${PRODUCT_NAME} home`}>
          <N10Mark size={32} />
          <div className="sidebar-org-text">
            <div className="sidebar-org-name">{PRODUCT_NAME}</div>
            <div className="sidebar-org-ver" style={{ textTransform: 'none', letterSpacing: 0 }}>Answers from Naren&rsquo;s calls</div>
          </div>
        </Link>

        {/* N10's thread list is portalled in here by the page (see AskNaren). One live page, so
            there is no page nav: a single link to where you already are changes nothing. */}
        <div id={SIDEBAR_SLOT_ID} className="sidebar-slot" />

        {user?.isAdmin && (
          <nav aria-label="Admin" className="px-2 pb-1">
            <Link href="/admin" className="sidebar-item" title={sidebarOpen ? undefined : 'Manage users'}>
              <span className="sidebar-item-dot" aria-hidden="true" />
              <span className="sidebar-item-label">Manage users</span>
            </Link>
          </nav>
        )}

        {user && (
          <div className="sidebar-user" title={sidebarOpen ? undefined : `${user.name} · ${user.email}`}>
            <div className="sidebar-user-avatar" aria-hidden="true">{initials(user.name)}</div>
            <div className="sidebar-user-info">
              <div className="sidebar-user-name">{user.name}</div>
              <div className="sidebar-user-meta" style={{ textTransform: 'none', letterSpacing: 0 }}>{user.email}</div>
            </div>
            <div className="sidebar-signout text-[12px] text-ink-2">
              <SignOutButton />
            </div>
          </div>
        )}
      </aside>

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
          <div className="topbar-controls" style={{ marginLeft: 'auto' }}>
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
          </div>
        </header>

        <main className="app-main">{children}</main>
      </div>
    </div>
  );
}
