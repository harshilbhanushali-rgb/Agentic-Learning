'use client';
import type { ReactNode } from 'react';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { MenuIcon, SunIcon, MoonIcon } from '@/components/icons';

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
const NAV_ITEMS = [{ href: '/ask-naren', label: 'Ask Naren' }];

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
  user: { name: string; email: string } | null;
}) {
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [darkMode, setDarkMode] = useState(false);

  useEffect(() => {
    setMounted(true);
    if (localStorage.getItem('cs-sidebar') === 'closed') setSidebarOpen(false);
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
      localStorage.setItem('cs-sidebar', o ? 'closed' : 'open');
      return !o;
    });
  };

  return (
    <div className={`app-layout${sidebarOpen ? '' : ' sidebar-collapsed'}`}>
      <aside className="app-sidebar" aria-label="Application sidebar">
        <div className="sidebar-org">
          <div className="sidebar-org-logo">CC</div>
          <div className="sidebar-org-text">
            <div className="sidebar-org-name">Customer Champi…</div>
            <div className="sidebar-org-ver">CS · V2.0</div>
          </div>
        </div>

        <nav className="sidebar-nav" aria-label="Pages">
          {NAV_ITEMS.map(({ href, label }) => {
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
              </Link>
            );
          })}
        </nav>

        <div className="sidebar-spacer" />

        {user && (
          <div className="sidebar-user" title={sidebarOpen ? undefined : `${user.name} · ${user.email}`}>
            <div className="sidebar-user-avatar" aria-hidden="true">{initials(user.name)}</div>
            <div className="sidebar-user-info">
              <div className="sidebar-user-name">{user.name}</div>
              <div className="sidebar-user-meta" style={{ textTransform: 'none', letterSpacing: 0 }}>{user.email}</div>
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
