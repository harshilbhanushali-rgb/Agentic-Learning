import { randomBytes, scrypt, timingSafeEqual } from 'node:crypto';

/**
 * Password hashing (ADR 0011): `node:crypto` scrypt, no dependency.
 *
 * AT OWASP'S MINIMUM, NOT NODE'S DEFAULT. Node defaults to N=2^14, below OWASP's floor of
 * N=2^17 (r=8, p=1). That needs 128 * N * r = 128 MiB per hash, past Node's default
 * `maxmem` of 32 MiB, so `maxmem` is raised explicitly -- without it scrypt throws rather
 * than silently weakening, but it is the first thing someone "fixing" the error would lower.
 *
 * THE PARAMETERS TRAVEL IN THE HASH (`scrypt$ln=17,r=8,p=1$salt$key`), so raising them later
 * needs no migration: old hashes still verify under the parameters they were made with.
 */
const LOG_N = 17;
const R = 8;
const P = 1;
const KEY_BYTES = 32;
const SALT_BYTES = 16;
const MAXMEM = 256 * 1024 * 1024;

/** Accepted when reading a stored hash. Bounds a tampered row's cost rather than trusting it. */
const MIN_LOG_N = 14;
const MAX_LOG_N = 20;

/** Admin-set passwords only (there is no self-service), so this bounds the CLI, and caps the
 *  work a sign-in attempt can make the server do. */
export const MIN_PASSWORD_LENGTH = 12;
export const MAX_PASSWORD_LENGTH = 1024;

function derive(password: string, salt: Buffer, logN: number, r: number, p: number): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    // Async: runs on libuv's threadpool, so a sign-in does not block every other request.
    scrypt(password.normalize('NFKC'), salt, KEY_BYTES, { N: 2 ** logN, r, p, maxmem: MAXMEM }, (err, key) =>
      err ? reject(err) : resolve(key),
    );
  });
}

export async function hashPassword(password: string): Promise<string> {
  const salt = randomBytes(SALT_BYTES);
  const key = await derive(password, salt, LOG_N, R, P);
  return `scrypt$ln=${LOG_N},r=${R},p=${P}$${salt.toString('base64')}$${key.toString('base64')}`;
}

/**
 * True only for a well-formed hash that matches. Anything malformed is a `false`, never a
 * throw: a corrupt row must read as "wrong password", not as a server error on sign-in.
 */
export async function verifyPassword(password: string, stored: string): Promise<boolean> {
  if (password.length > MAX_PASSWORD_LENGTH) return false;
  const parts = stored.split('$');
  if (parts.length !== 4 || parts[0] !== 'scrypt') return false;
  const params = /^ln=(\d+),r=(\d+),p=(\d+)$/.exec(parts[1]);
  if (!params) return false;
  const [logN, r, p] = params.slice(1).map(Number);
  if (logN < MIN_LOG_N || logN > MAX_LOG_N || r !== R || p !== P) return false;
  const salt = Buffer.from(parts[2], 'base64');
  const expected = Buffer.from(parts[3], 'base64');
  if (salt.length !== SALT_BYTES || expected.length !== KEY_BYTES) return false;
  const actual = await derive(password, salt, logN, r, p);
  return timingSafeEqual(actual, expected);
}

let dummy: Promise<string> | undefined;

/**
 * A hash to verify against when there is no real one -- an unknown email, or a user whose
 * password was cleared. Doing the same scrypt work either way means response time does not
 * say whether an email belongs to a user.
 */
export function dummyHash(): Promise<string> {
  dummy ??= hashPassword(randomBytes(32).toString('base64'));
  return dummy;
}
