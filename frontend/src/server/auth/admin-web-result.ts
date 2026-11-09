/**
 * What an /admin form returns (ADR 0016). In its own file, with no imports, because the page's
 * client component needs it: importing it from admin-web.ts would pull node:crypto and the
 * user store into the browser bundle.
 */
export interface AdminResult {
  ok: string | null;
  error: string | null;
  /** Set only when the page generated the password, so the admin can hand it over. */
  password: string | null;
}

export const EMPTY_RESULT: AdminResult = { ok: null, error: null, password: null };
