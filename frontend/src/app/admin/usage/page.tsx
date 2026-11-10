import { UsageDashboard } from '@/components/admin/usage/UsageDashboard';
import { type UsageReport, loadUsage, parseRange } from '@/server/analytics';
import { requireAdmin } from '@/server/auth/admins';
import { db } from '@/server/db';

/**
 * How the team uses Ask Naren: who asks, how often, whether they like the answers, and what
 * it cannot answer. Admins only, like /admin; anyone else gets a 404. Read-only.
 */
export default async function UsagePage({ searchParams }: { searchParams: { range?: string } }) {
  await requireAdmin('/admin/usage');
  const range = parseRange(searchParams.range);

  let report: UsageReport | null = null;
  try {
    report = await loadUsage(db(), range);
  } catch (cause) {
    console.error('[ask-naren] usage page could not load analytics:', cause);
  }

  return <UsageDashboard range={range} report={report} />;
}
