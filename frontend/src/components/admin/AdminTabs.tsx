import Link from 'next/link';

const TABS = [
  { id: 'people', label: 'People', href: '/admin' },
  { id: 'usage', label: 'Usage', href: '/admin/usage' },
] as const;

/** The two admin pages: manage people, and see how they use Ask Naren. */
export function AdminTabs({ current }: { current: (typeof TABS)[number]['id'] }) {
  return (
    <nav aria-label="Admin sections" className="flex gap-1 border-b border-line">
      {TABS.map(t => (
        <Link
          key={t.id}
          href={t.href}
          aria-current={t.id === current ? 'page' : undefined}
          className={`-mb-px border-b-2 px-3.5 py-2.5 text-[14px] font-semibold transition-colors duration-fast ease-out-quart ${
            t.id === current ? 'border-primary text-ink' : 'border-transparent text-ink-2 hover:text-ink'
          }`}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
