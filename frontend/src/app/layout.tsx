import type { ReactNode } from 'react';
import { GeistSans } from 'geist/font/sans';
import { GeistMono } from 'geist/font/mono';
import AppShell from '@/components/AppShell';
import './globals.css';

const geist = GeistSans;
const geistMono = GeistMono;

export const metadata = {
  title: 'Joveo CS Platform',
  description: 'Knowledge platform for Customer Champions',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${geist.variable} ${geistMono.variable}`} suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{ __html: `try{var t=localStorage.getItem('cs-theme');if(t==='dark')document.documentElement.dataset.theme='dark';}catch(e){}` }} />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
