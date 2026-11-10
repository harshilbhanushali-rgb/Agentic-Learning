import { NextResponse, type NextRequest } from 'next/server';

import {
  encodeGoogleFlow,
  googleAuthUrl,
  googleConfig,
  googleFlowCookieName,
  googleFlowCookieOptions,
  newGoogleFlow,
} from '@/server/auth/google';

/* Per request, always. Without this Next 14 builds a GET handler as a STATIC route: one
 * response computed at build time -- one fixed state and nonce, or a fixed "google_off" --
 * served to everyone. The build output marks it `○` when that has happened. */
export const dynamic = 'force-dynamic';

/** Step 1 of Google sign-in (src/server/auth/google.ts): remember this attempt, go to Google. */
export async function GET(request: NextRequest): Promise<Response> {
  const config = googleConfig();
  if (!config) return seeOther('/login?error=google_off');

  const flow = newGoogleFlow(request.nextUrl.searchParams.get('next'));
  const res = seeOther(googleAuthUrl(config, flow));
  res.cookies.set(googleFlowCookieName(), encodeGoogleFlow(flow), googleFlowCookieOptions());
  return res;
}

/** A redirect with a path-only Location where it is ours, so it is right behind any proxy. */
function seeOther(location: string): NextResponse {
  return new NextResponse(null, { status: 303, headers: { location } });
}
