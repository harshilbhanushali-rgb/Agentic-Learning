/**
 * Where the Ask Naren service is, and proof that it IS the service -- before any CSM's
 * question is sent there.
 *
 * WHY THIS EXISTS (2026-09-29). Production was configured with
 * `ASK_NAREN_SERVICE_URL=http://ask-naren-be.joveo.prod.com/`. That is a subdomain of
 * `prod.com`, a wildcard domain Joveo does not own: every name under it resolves to the same
 * third-party LiteSpeed host. So every question -- the CSM's situation and the replayed thread,
 * with client names and Naren's words -- was POSTed in plain HTTP to a stranger's server, which
 * answered with an HTML 404. Nothing here could tell. The route only noticed that the reply
 * was not JSON, after the data had already left.
 *
 * Two checks now run BEFORE a question is sent, and neither one carries CSM data:
 *
 * 1. The URL must name an INTERNAL host: localhost, a private IP, a cluster name (dot-less,
 *    `*.svc`, `*.cluster.local`), a `*.joveo.com` name, or a host listed in
 *    `ASK_NAREN_ALLOWED_SERVICE_HOSTS`. Anything else is refused outright. A typo in a domain
 *    is exactly how data goes to the public internet, and no reply can undo it.
 * 2. `GET <url>/health` must return the service's own `{"status": "ok"}`. A host that
 *    resolves but is not the service -- a proxy, an ingress with no route, a stranger's
 *    server -- fails here, with a log line that says what answered instead.
 *
 * If either check fails, the CSM gets the ordinary `service_unreachable` decline, and the
 * operator gets a log line naming the cause.
 */

export const DEFAULT_SERVICE_URL = 'http://127.0.0.1:8787';

export type ServiceTarget = { ok: true; base: string } | { ok: false; reason: string };

/** Hostname suffixes that are internal by construction. */
const INTERNAL_SUFFIXES = ['.svc', '.svc.cluster.local', '.cluster.local', '.internal', '.local', '.joveo.com'];

function isPrivateIPv4(host: string): boolean {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
}

function isInternalHost(host: string, allowed: string[]): boolean {
  const h = host.toLowerCase().replace(/^\[|\]$/g, '');
  if (allowed.some(a => h === a || (a.startsWith('.') && h.endsWith(a)))) return true;
  if (h === 'localhost' || h === '::1' || /^f[cd][0-9a-f]{2}:/.test(h)) return true;
  if (isPrivateIPv4(h)) return true;
  if (!h.includes('.') && !h.includes(':')) return true; // a Kubernetes Service's short name
  return INTERNAL_SUFFIXES.some(s => h.endsWith(s));
}

/**
 * Parse and check `ASK_NAREN_SERVICE_URL`. Trailing slashes are dropped, because the route
 * appends `/ask` itself and `host//ask` is a different path to an ingress.
 */
export function resolveServiceUrl(raw: string | undefined, allowedRaw: string | undefined): ServiceTarget {
  const value = (raw ?? '').trim() || DEFAULT_SERVICE_URL;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return { ok: false, reason: `ASK_NAREN_SERVICE_URL is not a URL: ${JSON.stringify(value)}` };
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return { ok: false, reason: `ASK_NAREN_SERVICE_URL must be http(s), got ${url.protocol}` };
  }
  if (url.username || url.password || url.search || url.hash) {
    return { ok: false, reason: 'ASK_NAREN_SERVICE_URL must not carry credentials, a query or a fragment' };
  }
  const allowed = (allowedRaw ?? '')
    .split(',')
    .map(s => s.trim().toLowerCase())
    .filter(Boolean);
  if (!isInternalHost(url.hostname, allowed)) {
    return {
      ok: false,
      reason:
        `ASK_NAREN_SERVICE_URL points at ${url.hostname}, which is not an internal address. ` +
        'Questions are NOT being sent there. Use the service\'s in-cluster address ' +
        '(http://<service>.<namespace>.svc.cluster.local:80), or, if this host really is the Ask ' +
        'Naren service, list it in ASK_NAREN_ALLOWED_SERVICE_HOSTS.',
    };
  }
  return { ok: true, base: `${url.origin}${url.pathname.replace(/\/+$/, '')}` };
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

/** A failed identity check is retried after this long, so a service that was starting up
 *  (or briefly down) is picked up without a restart, and a wrong URL is not probed on every
 *  single question. */
export const RECHECK_AFTER_MS = 30_000;
const PROBE_TIMEOUT_MS = 5_000;

/** Is the thing at `base` the Ask Naren service? Its liveness endpoint answers exactly
 *  `{"status": "ok"}` (Brain/ask_naren/api/). Nothing a CSM typed is sent. */
export async function probeService(base: string, fetchImpl: Fetch = fetch): Promise<{ ok: true } | { ok: false; reason: string }> {
  let res: Response;
  try {
    res = await fetchImpl(`${base}/health`, { cache: 'no-store', signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) });
  } catch (cause) {
    return { ok: false, reason: `GET ${base}/health failed: ${cause instanceof Error ? cause.message : String(cause)}` };
  }
  const type = res.headers.get('content-type') ?? 'no content-type';
  const server = res.headers.get('server');
  const text = await res.text().catch(() => '');
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    body = undefined;
  }
  if (res.status === 200 && (body as { status?: unknown } | undefined)?.status === 'ok') return { ok: true };
  return {
    ok: false,
    reason:
      `GET ${base}/health returned ${res.status} ${type}${server ? ` (Server: ${server})` : ''}, not the Ask Naren ` +
      'service\'s {"status": "ok"} -- that URL is not the service. No question was sent to it.',
  };
}

/**
 * The verified service base, memoised: a pass is kept for the life of the process, a failure
 * for RECHECK_AFTER_MS. `now` and `fetchImpl` are injectable for tests.
 */
export function createServiceGate(target: ServiceTarget, fetchImpl?: Fetch, now: () => number = Date.now) {
  let verified = false;
  let failedAt = -Infinity;
  let lastReason = '';
  return async function serviceBase(): Promise<ServiceTarget> {
    if (!target.ok) return target;
    if (verified) return target;
    if (now() - failedAt < RECHECK_AFTER_MS) return { ok: false, reason: lastReason };
    const probe = await probeService(target.base, fetchImpl);
    if (probe.ok) {
      verified = true;
      return target;
    }
    failedAt = now();
    lastReason = probe.reason;
    return { ok: false, reason: probe.reason };
  };
}
