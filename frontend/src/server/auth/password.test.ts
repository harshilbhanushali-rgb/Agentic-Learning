import { describe, expect, it } from 'vitest';

import { MAX_PASSWORD_LENGTH, dummyHash, hashPassword, verifyPassword } from './password';

describe('password hashing', () => {
  it('verifies the password it hashed, and nothing else', async () => {
    const hash = await hashPassword('correct horse battery');
    expect(await verifyPassword('correct horse battery', hash)).toBe(true);
    expect(await verifyPassword('correct horse batterY', hash)).toBe(false);
    expect(await verifyPassword('', hash)).toBe(false);
  });

  it("is at OWASP's minimum and carries its parameters, so they can rise without a migration", async () => {
    const hash = await hashPassword('p');
    expect(hash).toMatch(/^scrypt\$ln=17,r=8,p=1\$[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+$/);
  });

  it('salts: the same password hashes differently each time', async () => {
    expect(await hashPassword('same')).not.toBe(await hashPassword('same'));
  });

  it('treats visually identical Unicode spellings as the same password', async () => {
    const composed = 'café-password';
    const decomposed = 'café-password';
    expect(await verifyPassword(decomposed, await hashPassword(composed))).toBe(true);
  });

  it('reads a malformed or tampered hash as a wrong password, never a throw', async () => {
    const good = await hashPassword('pw');
    const [, params, salt, key] = good.split('$');
    for (const bad of [
      '',
      'not-a-hash',
      `bcrypt$${params}$${salt}$${key}`,
      `scrypt$ln=30,r=8,p=1$${salt}$${key}`, // a cost that would pin the CPU
      `scrypt$ln=4,r=8,p=1$${salt}$${key}`, // a cost too cheap to accept
      `scrypt$${params}$${salt}$${key.slice(0, 8)}`,
      `scrypt$${params}$$${key}`,
    ]) {
      await expect(verifyPassword('pw', bad)).resolves.toBe(false);
    }
  });

  it('refuses an oversized password without doing the work', async () => {
    const hash = await hashPassword('pw');
    expect(await verifyPassword('x'.repeat(MAX_PASSWORD_LENGTH + 1), hash)).toBe(false);
  });

  it('keeps one dummy hash, which no password is likely to match', async () => {
    const a = await dummyHash();
    expect(await dummyHash()).toBe(a);
    expect(await verifyPassword('', a)).toBe(false);
  });
});
