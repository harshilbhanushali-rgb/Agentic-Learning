export function NewbieGreeting() {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-4">
        <span className="text-xs font-semibold text-ink-2">Workspace · Today</span>
        <div className="flex items-center gap-2">
          <button className="inline-flex items-center h-7 px-3 rounded-sm border border-line bg-bg text-xs font-medium text-ink cursor-pointer transition duration-fast ease-out-quart hover:bg-primary-subtle hover:border-primary hover:text-primary">Phase 2 · Understand</button>
          <button className="inline-flex items-center gap-2 h-7 px-3 rounded-sm border border-line bg-transparent text-xs font-semibold text-ink-2 cursor-pointer transition duration-fast ease-out-quart hover:bg-surface hover:text-ink">+ New scratch note</button>
        </div>
      </div>
      <h1 className="text-[clamp(1.5rem,3vw,2rem)] font-extrabold text-ink leading-snug tracking-[-0.025em] max-w-[640px] text-balance">
        Welcome back, Riya. You&apos;re 41 days into your track.
      </h1>
      <p className="text-sm text-ink-2 leading-base max-w-[580px]">
        Phase 2 of 3 — Understand. Three modules and one Apply simulation queued for today.
      </p>
    </div>
  );
}
