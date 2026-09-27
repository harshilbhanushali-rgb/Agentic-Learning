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
 * search, the Veteran/Newbie switch, notifications, the mock "Today" items and profile) is
 * kept at src/components/_archive/AppShell.tsx. None of that did anything real: bringing it
 * back is restoring those files, not rebuilding them.
 *
 * NO MODE SWITCH, DELIBERATELY. Ask Naren renders identically in both modes, so with it the
 * only page, a Veteran/Newbie toggle would be a control that changes nothing. The
 * `cs-mode` key and `useMode` stay for the archived pages.
 */
const NAV_ITEMS = [{ href: '/ask-naren', label: 'Ask Naren' }];

export default function AppShell({ children }: { children: ReactNode }) {
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
