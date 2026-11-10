import type { ReactNode } from 'react';
import { GeistSans } from 'geist/font/sans';
import { GeistMono } from 'geist/font/mono';
import AppShell from '@/components/AppShell';
import { getCurrentUser } from '@/server/auth/current-user';
import { isAdmin } from '@/server/auth/admin-list';
import './globals.css';

const geist = GeistSans;
const geistMono = GeistMono;

export const metadata = {
  title: 'N10 · Joveo',
  description: 'Answers from Naren’s real client calls, for Support and Implementation',
};

/**
 * Who is signed in, for the sidebar -- never a gate. The page that needs a user still asks
 * for itself (issue #42: a layout is not where access is decided). A store fault here shows
 * no user rather than failing every page; the page underneath reports the outage properly
 * (issue #40). `getCurrentUser` is cached per request, so this is not a second read.
 */
async function sidebarUser(): Promise<{ name: string; email: string; isAdmin: boolean } | null> {
  try {
    const user = await getCurrentUser();
    return user ? { name: user.name, email: user.email, isAdmin: isAdmin(user) } : null;
  } catch {
    return null;
  }
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const user = await sidebarUser();
  return (
    <html lang="en" className={`${geist.variable} ${geistMono.variable}`} suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{ __html: `try{var t=localStorage.getItem('cs-theme');if(t==='dark')document.documentElement.dataset.theme='dark';}catch(e){}` }} />
        <AppShell user={user}>{children}</AppShell>
      </body>
    </html>
  );
}
