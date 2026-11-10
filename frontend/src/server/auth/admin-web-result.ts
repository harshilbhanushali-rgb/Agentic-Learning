/**
 * What an /admin form returns (ADR 0016). In its own file, with no imports, because the page's
 * client component needs it: importing it from admin-web.ts would pull the user store into the
 * browser bundle.
 */
export interface AdminResult {
  ok: string | null;
  error: string | null;
}

export const EMPTY_RESULT: AdminResult = { ok: null, error: null };
