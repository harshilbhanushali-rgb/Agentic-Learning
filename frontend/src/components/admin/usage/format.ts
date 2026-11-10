/** Display helpers for the Usage page. Every date is shown in India time. */

const TZ = 'Asia/Kolkata';

/** "Tue 10 Nov" (or "10 Nov") for a `YYYY-MM-DD` India-time day. */
export function formatDay(day: string, { weekday = true } = {}): string {
  const d = new Date(`${day}T12:00:00+05:30`);
  return d.toLocaleDateString('en-GB', {
    timeZone: TZ, day: 'numeric', month: 'short', ...(weekday ? { weekday: 'short' } : {}),
  });
}

function dayKey(t: Date): string {
  return t.toLocaleDateString('en-CA', { timeZone: TZ });
}

/** "Today 14:20", "Yesterday", or "6 Nov", relative to `now`. */
export function formatWhen(at: Date | string, now: Date): string {
  const t = new Date(at);
  const today = dayKey(now);
  const yesterday = dayKey(new Date(now.getTime() - 86_400_000));
  if (dayKey(t) === today) {
    return `Today ${t.toLocaleTimeString('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit' })}`;
  }
  if (dayKey(t) === yesterday) return 'Yesterday';
  return t.toLocaleDateString('en-GB', { timeZone: TZ, day: 'numeric', month: 'short' });
}

/** Whole percent, or null when there is nothing to divide by. */
export function pct(part: number, whole: number): number | null {
  return whole > 0 ? Math.round((part / whole) * 100) : null;
}

/** Scenario keys as people read them: "ats_integration" -> "Ats integration". */
export function topicLabel(key: string | null): string {
  if (!key) return 'No single topic';
  const s = key.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function seconds(n: number): string {
  return n < 60 ? `${Math.round(n)}s` : `${Math.floor(n / 60)}m ${Math.round(n % 60)}s`;
}
