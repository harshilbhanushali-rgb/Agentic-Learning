// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';

import { RECHECK_AFTER_MS, createServiceGate, probeService, resolveServiceUrl } from './serviceUrl';

const ok = (base: string) => ({ ok: true as const, base });

describe('resolveServiceUrl', () => {
  it('refuses the production URL that sent questions to a third party (2026-09-29)', () => {
    const r = resolveServiceUrl('http://ask-naren-be.joveo.prod.com/', undefined);
    expect(r.ok).toBe(false);
    expect(!r.ok && r.reason).toMatch(/ask-naren-be\.joveo\.prod\.com, which is not an internal address/);
    expect(!r.ok && r.reason).toMatch(/NOT being sent/);
  });

  it('defaults to the local service when unset or blank', () => {
    expect(resolveServiceUrl(undefined, undefined)).toEqual(ok('http://127.0.0.1:8787'));
    expect(resolveServiceUrl('   ', undefined)).toEqual(ok('http://127.0.0.1:8787'));
  });

  it('drops trailing slashes, so /ask is never //ask', () => {
    // :80 is http's default port, so it is the same address and the URL parser drops it.
    expect(resolveServiceUrl('http://ask-naren:80/', undefined)).toEqual(ok('http://ask-naren'));
    expect(resolveServiceUrl('http://ask-naren:8787/', undefined)).toEqual(ok('http://ask-naren:8787'));
    expect(resolveServiceUrl('http://ask-naren.team.svc.cluster.local//', undefined)).toEqual(
      ok('http://ask-naren.team.svc.cluster.local'),
    );
    expect(resolveServiceUrl('http://10.0.4.7:8080/prefix/', undefined)).toEqual(ok('http://10.0.4.7:8080/prefix'));
  });

  it('accepts internal hosts: cluster names, private IPs, localhost, *.joveo.com', () => {
    for (const url of [
      'http://coder-pets-tray-ask-naren',
      'http://ask-naren.team.svc',
      'http://ask-naren.team.svc.cluster.local:80',
      'http://localhost:8787',
      'http://127.0.0.1:8787',
      'http://10.1.2.3',
      'http://172.16.0.1',
      'http://172.31.135.97:80',
      'http://192.168.1.10',
      'http://[::1]:8787',
      'https://ask-naren.prod.joveo.com',
    ]) {
      expect(resolveServiceUrl(url, undefined).ok, url).toBe(true);
    }
  });

  it('refuses public hosts and look-alike domains', () => {
    for (const url of [
      'http://example.com',
      'http://joveo.com.evil.example',
      'http://ask-naren.joveo.prod.com',
      'http://172.32.0.1',
      'http://8.8.8.8',
      'https://myjoveo.com',
    ]) {
      expect(resolveServiceUrl(url, undefined).ok, url).toBe(false);
    }
  });

  it('allows a host only when an operator lists it, exactly or by .suffix', () => {
    expect(resolveServiceUrl('http://ask-naren.partner.net', 'ask-naren.partner.net').ok).toBe(true);
    expect(resolveServiceUrl('http://a.b.partner.net', ' other.org , .partner.net ').ok).toBe(true);
    expect(resolveServiceUrl('http://partner.net.evil.example', '.partner.net').ok).toBe(false);
  });

  it('refuses a malformed URL, a non-http scheme, credentials, a query or a fragment', () => {
    for (const url of ['not a url', 'ftp://ask-naren', 'http://user:pw@ask-naren', 'http://ask-naren/?x=1', 'http://ask-naren/#a']) {
      expect(resolveServiceUrl(url, undefined).ok, url).toBe(false);
    }
  });
});

/** A stand-in for fetch with fetch's own parameters, so a mock's calls can be inspected. */
function reply(body: string, init: ResponseInit = {}) {
  return async (_input: string, _init?: RequestInit) => new Response(body, init);
}

describe('probeService', () => {
  it("passes only the service's own liveness answer", async () => {
    const f = vi.fn(reply(JSON.stringify({ status: 'ok' }), { status: 200, headers: { 'content-type': 'application/json' } }));
    expect(await probeService('http://ask-naren', f)).toEqual({ ok: true });
    expect(f.mock.calls[0][0]).toBe('http://ask-naren/health');
  });

  it('names what answered instead -- the production failure was an HTML 404 from LiteSpeed', async () => {
    const f = reply('<!DOCTYPE html><title>404 Not Found</title>', {
      status: 404,
      headers: { 'content-type': 'text/html', server: 'LiteSpeed' },
    });
    const r = await probeService('http://x', f);
    expect(r.ok).toBe(false);
    expect(!r.ok && r.reason).toMatch(/returned 404 text\/html \(Server: LiteSpeed\)/);
  });

  it('fails on JSON that is not the liveness answer, and on a network error', async () => {
    expect((await probeService('http://x', reply(JSON.stringify({ outcome: 'declined' }), { status: 200 }))).ok).toBe(false);
    const down = async () => {
      throw new Error('connect ECONNREFUSED');
    };
    const r = await probeService('http://x', down);
    expect(!r.ok && r.reason).toMatch(/ECONNREFUSED/);
  });
});

describe('createServiceGate', () => {
  it('never probes a refused URL', async () => {
    const f = vi.fn();
    const gate = createServiceGate({ ok: false, reason: 'bad host' }, f);
    expect(await gate()).toEqual({ ok: false, reason: 'bad host' });
    expect(f).not.toHaveBeenCalled();
  });

  it('probes once, then trusts the service for the life of the process', async () => {
    const f = vi.fn(reply(JSON.stringify({ status: 'ok' }), { status: 200 }));
    const gate = createServiceGate(ok('http://ask-naren'), f);
    expect(await gate()).toEqual(ok('http://ask-naren'));
    expect(await gate()).toEqual(ok('http://ask-naren'));
    expect(f).toHaveBeenCalledTimes(1);
  });

  it('remembers a failure for a while, then checks again -- a starting service is picked up', async () => {
    let t = 0;
    let up = false;
    const f = vi.fn(async () =>
      up ? new Response(JSON.stringify({ status: 'ok' }), { status: 200 }) : new Response('nope', { status: 503 }),
    );
    const gate = createServiceGate(ok('http://ask-naren'), f, () => t);
    expect((await gate()).ok).toBe(false);
    t += RECHECK_AFTER_MS - 1;
    expect((await gate()).ok).toBe(false);
    expect(f).toHaveBeenCalledTimes(1);
    up = true;
    t += 1;
    expect(await gate()).toEqual(ok('http://ask-naren'));
    expect(f).toHaveBeenCalledTimes(2);
  });
});
