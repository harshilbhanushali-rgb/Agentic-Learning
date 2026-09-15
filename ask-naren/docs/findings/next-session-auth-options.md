# Session login options for this Next 14 App Router app

**Status: RESEARCH, 2026-09-15. Issue #35, part of #34.** This file does not recommend
anything — the call is made by a human in #36. Its job is to make that call well-informed.

**Everything below is sourced.** Where a claim could not be verified against a primary
source it is marked **UNVERIFIED** and says so rather than being described plausibly. A
confidently wrong API description is worse than a gap, because the next person builds on it.

---

## The question

What are the realistic options for **admin-seeded email/password login with a server-side
session** in this app, and what does each cost to swap for Google Workspace later?

The swap cost is the column that decides. The shape settled in #34 is that the account is
keyed on the `@joveo.com` email, so moving to Workspace later changes **how identity is
proved**, not **what identity is** — no re-keying of threads or analytics rows.

## The app this has to fit

| | |
| --- | --- |
| Next.js | `^14.2.15` (`frontend/package.json`); Next 14 requires Node `>=18.17.0` |
| Runtime deps | `clsx`, `geist`, `motion`, `next`, `react`, `react-dom`, `tailwind-merge`. **Seven.** No auth library, no data-fetching library, no state library, no icon library, no ORM, no Postgres driver |
| Server seams | Exactly one: `frontend/src/app/api/ask-naren/route.ts`, a byte-for-byte proxy |
| Env | One variable, `ASK_NAREN_SERVICE_URL`. **Deliberately no `NEXT_PUBLIC_*`**, so nothing is inlined into the client bundle (`frontend/.env.example`) |
| TypeScript | `strict: true`; `npm run build` is the only gate — there are no tests |
| Today's thread | `localStorage['cs-ask-naren-thread-v1']`, one key for everyone, abandoned by #34 with no migration (`frontend/src/lib/thread.ts`) |

Two consequences that constrain every option below:

1. **A Postgres driver has to be added no matter what.** Accounts live in Brain's Neon
   instance, written by the Next app (#34). `pg` / `postgres` / `@neondatabase/serverless`
   is a shared cost, not a differentiator between the options. It is excluded from the
   dependency column below for that reason.
2. **Middleware cannot read the database.** Next 14: *"Middleware currently only supports
   the Edge runtime. The Node.js runtime can not be used."*
   ([Next 14.2.35 Middleware docs](https://nextjs.org/docs/14/app/building-your-application/routing/middleware),
   lastUpdated 2024-03-25). No `pg`, no `node:crypto` scrypt in `middleware.ts`. A
   server-side session record can only be *checked* in a Server Component, Route Handler or
   Server Action — middleware can do an optimistic cookie-presence check and nothing more.
   Node middleware became available experimentally in **Next 15.2** and is the documented
   path in **Next 16** — *not in 14*.

---

## Comparison

| | A. Opaque token + session table | B. Signed/encrypted cookie (`jose`) | C. `iron-session` | D. Auth.js v5 (`next-auth`) + Credentials | E. Better Auth |
| --- | --- | --- | --- | --- | --- |
| **Mechanism** | Random token in cookie, row in Postgres | Self-contained JWT/JWE cookie | Self-contained sealed cookie, library-managed | Framework: routes + callbacks + JWE cookie | Framework: routes + session table + cookie |
| **Source of truth** | **Server (Postgres row)** | **Cookie** | **Cookie** | **Cookie** (forced, see D) | **Server (`session` table)** |
| **Logout revokes immediately** | Yes (delete row) | No — cookie valid until `exp` unless a blocklist is added | No — sealed until `ttl`; README: *do not use `ttl: 0` for authentication* | No (same as B) | Yes (`revokeSession`) |
| **Survives server restart** | Yes | Yes, if the secret is in env | Yes, if the password is in env | Yes, if `AUTH_SECRET` is in env | Yes |
| **Password hashing** | You choose (`node:crypto` scrypt, or `@node-rs/argon2`) | You choose | You choose | **You write it** — `authorize()` is your code | **Provided** — scrypt, overridable |
| **Owns a schema** | No — you write the DDL | No | No | No (Credentials writes nothing) | **Yes** — `user` / `session` / `account` / `verification`, remappable |
| **Google Workspace swap** | Add an OIDC callback that looks up the same row by email; session mechanism untouched | Same, but you write the whole OIDC dance | Same as B | Add `Google` provider + **`allowDangerousEmailAccountLinking: true`**, off by default | Add `socialProviders.google`; links by email when the provider verified it |
| **New runtime deps** | 0–1 (`@node-rs/argon2` if not using `node:crypto`) | 1 (`jose`, zero transitive deps) | 1 (`iron-session` → `cookie`, `iron-webcrypto`) | 1 (`next-auth` → `@auth/core` → `jose`, `oauth4webapi`, `@panva/hkdf`, **`preact` + `preact-render-to-string`**) | 1 (`better-auth` → ~15 direct deps incl. `zod`, `kysely`, `nanostores`, `@noble/*`, `jose`, 5 adapter packages) |
| **Reaches the client bundle** | No | No | No | Only if you import `next-auth/react`; avoidable | Only if you import `better-auth/react`; the server-action flow is documented |
| **Release status** | n/a | 6.2.12, stable | 9.0.1, stable, **Node ≥ 22.13, ESM-only** | **`5.0.0-beta.32`** — still beta; v4 `4.24.15` is the stable line | 1.7.5, stable |
| **Project status** | n/a | Maintained | Maintained | **Now maintained by the Better Auth team; new projects steered to Better Auth** | Active; joined Vercel 2026-07-07 |

---

## Before the options: three facts that reframe the choice

### 1. NextAuth is no longer the incumbent it looks like

`authjs.dev` carries the line **"The Auth.js project is now part of Better Auth"** at the
top of every page, with a *"Migrate to Better Auth"* nav item. The announcement
([better-auth.com/blog/authjs-joins-better-auth](https://better-auth.com/blog/authjs-joins-better-auth),
2025-09-22) says Auth.js *"is now being maintained and overseen by Better Auth team"*, that
they *"keep addressing security patches and urgent issues"*, and that **new projects are
recommended to start with Better Auth** *"unless there are some very specific feature gaps
(most notably stateless session management without a database)"*.

So the phrase "just add NextAuth" now means: adopt a library whose own maintainers point new
projects elsewhere.

### 2. `next-auth` v5 has been in beta for over two years

From the npm registry, read 2026-09-15:

| dist-tag | version | published |
| --- | --- | --- |
| `latest` | `4.24.15` | 2026-07-20 |
| `beta` | `5.0.0-beta.32` | 2026-07-20 |

`5.0.0-beta.25` was published 2024-10-19; there have been seven beta releases since. The
`auth()` helper, the App-Router-native API that every Next 14 tutorial uses, **exists only on
the beta line**. v4's App Router story is `getServerSession(authOptions)` plus a catch-all
route handler. Choosing "NextAuth for App Router" is choosing a beta.

`next-auth@5.0.0-beta.32` declares `peerDependencies.next: "^14.0.0-0 || ^15.0.0 || ^16.0.0"`,
so Next 14 is supported.

### 3. Lucia — the library most 2024 answers recommend for hand-rolled sessions — is gone

`lucia-auth.com` states Lucia **was deprecated in March 2025** and the site was updated in
July 2026. It is now a learning resource pointing at *The Auth Book*
(`auth.pilcrowonpaper.com`) and a single-file `auth_session.ts` you copy rather than install.
`oslo` (1.2.1) and `@oslojs/crypto` (1.0.1) have had no release since September 2024.

**This is not a dead end — it is the strongest argument for option A.** The ecosystem's own
answer to "how should I hand-roll a session?" stopped being a package and became a page of
code you own.

---

## A. Hand-rolled: opaque token + a session row in Postgres

**What it is.** On successful login a Server Action generates a cryptographically random
token, stores a row `(token_hash, account_id, expires_at, created_at)` in Postgres, and sets
the token in an `HttpOnly` cookie. Every protected read looks the row up. Nothing about the
session is derivable from the cookie — it is a pointer.

This is precisely the shape the Next 14 docs call a **Database Session**: *"Database session
management involves storing session data on the server, with the user's browser only
receiving a session ID. This ID references the session data stored server-side, without
containing the data itself."*
([Next 14 Authentication docs](https://nextjs.org/docs/14/app/building-your-application/authentication),
14.2.35, lastUpdated 2024-04-01.)

**Session carriage.** Cookie holds the raw token only. Set from a Server Action or Route
Handler — Next 14: *"HTTP does not allow setting cookies after streaming starts, so you must
use `.set()` in a Server Action or Route Handler"*
([`cookies` API reference, 14.2.35](https://nextjs.org/docs/14/app/api-reference/functions/cookies)).
In Next 14 `cookies()` is **synchronous**; `cookies().set(name, value, options)` with
`httpOnly`, `secure`, `sameSite`, `path`, `maxAge`/`expires`.

The Copenhagen Book's session chapter gives the design: *"It's important that the session ID
is sufficiently long and random, or else someone could impersonate other users by just
guessing their session IDs"*; *"Session IDs can be hashed before storage to provide an extra
level of security"*; *"Sessions can be invalidated by deleting it from both server and client
storage"*, and it recommends invalidating all of a user's sessions when the password changes.
Cookie attributes it requires: `HttpOnly`, `SameSite=Lax` (or `Strict`), `Secure`, `Path=/`,
and a `Max-Age`/`Expires` to persist. ([thecopenhagenbook.com/sessions](https://thecopenhagenbook.com/sessions))

Storing `sha256(token)` rather than the token means a Postgres dump does not hand over live
sessions. Compare with `crypto.timingSafeEqual(a, b)`, which *requires that both `a` and `b`
be of equal byte length* ([Node crypto docs](https://nodejs.org/api/crypto.html)) — a fixed
32-byte digest satisfies that by construction.

**Logout.** Delete the row, clear the cookie. Effective on the next request, everywhere.
**Restart.** Sessions survive; they live in Neon, not in process memory.

**Password hashing.** Nothing is provided; you choose. Two credible choices:

- `node:crypto`'s `scrypt` — **zero new dependencies**. Node's defaults are `N: 16384,
  r: 8, p: 1, maxmem: 32MB`, and the docs describe scrypt as *"designed to be computationally
  expensive"*. Note OWASP's minimum is **N = 2^17 (128 MiB), r = 8, p = 1**, which is 8× Node's
  default `N` and exceeds Node's default `maxmem` — so `maxmem` must be raised explicitly.
- `@node-rs/argon2` (2.2.1, native, no JS deps) for Argon2id, OWASP's **first choice**:
  *"Use the Argon2id variant since it provides a balanced approach to resisting both
  side-channel and GPU-based attacks"*, minimum 19 MiB / 2 iterations / 1 parallelism.

Avoid `bcrypt` here: OWASP lists it for **legacy systems only** and warns *"bcrypt has a
maximum length input length of 72 bytes for most implementations"*.
([OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html))

**Google Workspace swap — the cleanest.** The account row is keyed on email and the session
mechanism knows nothing about how the email was proved. Adding Workspace is: a `/api/auth/
google/callback` Route Handler that validates the ID token, reads `email` + `hd`, looks up
the existing account row, and creates the same session row it creates today. **No schema
change, no re-keying, no migration.** Nothing downstream of the session can tell the
difference.

**Cost.** You write, and own forever: token generation, hashing, cookie handling, the
session table and its DDL, expiry/extension, a login form + Server Action, logout, the
`getSession()` helper, and the OIDC callback at swap time. Roughly 150–250 lines you can read
in one sitting — and 150–250 lines nobody else patches when a CVE lands.

**Bundle.** Nothing reaches the client. Login is a `<form action={...}>` posting to a Server
Action, which Next 14 protects by comparing *"the Origin header to the Host header (or
`X-Forwarded-Host`). If these don't match, the request will be aborted."*
([Server Actions docs, 14.2.35](https://nextjs.org/docs/14/app/building-your-application/data-fetching/server-actions-and-mutations))
The same page warns: *"You should treat Server Actions as you would public-facing API
endpoints, and ensure that the user is authorized to perform the action."*

**Database fit — best.** You write the DDL, so it matches whatever #34's schema ticket
decides. Nothing else has an opinion.

---

## B. Hand-rolled stateless: a signed or encrypted cookie via `jose`

**What it is.** The same login flow as A, but instead of a database row the cookie carries
the session itself: a JWT signed (JWS) or encrypted (JWE) with a server secret, holding
`{ sub: account_id, email, exp }`. Verified on every request with no database round-trip.

This is the Next 14 docs' **Cookie-Based Session**: *"Cookie-based sessions manage user data
by storing encrypted session information directly in browser cookies… Encrypting session data
in cookies is key to safeguarding user information from unauthorized access. It ensures that
even if a cookie is stolen, the data inside remains unreadable."* The docs' own snippet is
`cookies().set('session', encryptedSessionData, { httpOnly: true, secure: …, maxAge: …, path:
'/' })` — with `encrypt()` left as an exercise.

**`jose` 6.2.12** is the standard filler for that gap: *"jose has no dependencies and it
exports tree-shakeable ESM"*, supporting Node, browsers, Cloudflare Workers, Deno, Bun and
Electron. The APIs are `SignJWT` / `jwtVerify` for signed tokens and `EncryptJWT` /
`jwtDecrypt` for encrypted ones. ([github.com/panva/jose](https://github.com/panva/jose))

> **Note the drift in what's written online.** The elaborate `lib/session.ts` +
> `lib/dal.ts` + `verifySession()` pattern with `jose` that dominates search results is from
> the **Next 15/16** authentication guide, not the Next 14 one. The Next 14 page (above) is
> much thinner: it shows `encrypt()`/`decrypt()` as placeholders and does not name a library.
> The code still works on 14, but do not cite the Next 14 docs as its source.

**Session carriage.** The cookie *is* the session. **Logout deletes the cookie and nothing
else** — a copy of that cookie taken before logout stays valid until `exp`. Auth.js's own
session-strategies page states the general problem plainly: you cannot expire a JWT before
its encoded expiry without maintaining *"a server-side blocklist of invalidated tokens"*.
A blocklist is a database table, i.e. option A with extra steps.

**Restart.** Fine, provided the secret comes from the environment and is stable across
instances. A secret generated at boot logs everyone out on every deploy.

**Password hashing.** Same as A — nothing provided.

**Google Workspace swap — clean.** Identical to A: the cookie's `sub` is your account id and
the OIDC callback just mints the same cookie. No migration.

**Cost vs A.** Saves one table and one query per request. Pays for it by losing revocation
and by adding a size ceiling (~4 KB per cookie). For a tool with a handful of CSMs where a
session row lookup is noise next to a 30-second answer deadline, that trade is unusually
unattractive — but it is the option that needs no session table at all, which matters if the
schema ticket wants to ship accounts before it ships sessions.

**Database fit.** Needs an accounts table only; no session table. Neutral.

---

## C. `iron-session` — option B, packaged

**What it is.** A small library that seals an arbitrary object into one encrypted cookie and
hands it back as a mutable JS object. *"The session data is stored in signed and encrypted
cookies which are decoded by your server code in a stateless fashion (= no network
involved)."* Built on `iron-webcrypto` (a Web-Crypto reimplementation of `@hapi/iron`).

**API, verified from the README on `main`:**

```js
import { cookies } from "next/headers";
import { getIronSession } from "iron-session";

const session = await getIronSession(await cookies(), { password: "...", cookieName: "..." });
```

`password` (≥ 32 chars, or `{2: "...", 1: "..."}` for rotation) and `cookieName` are the only
required options. `ttl` defaults to 14 days. `session.destroy()` is synchronous and
terminal: *"A `save()` after it is ignored, so a logout handler that calls both still signs
the user out."*

**Two things to weigh:**

- **v9.0.1 requires Node ≥ 22.13 and is ESM-only** (npm `engines`, and README: *"v9 needs
  Node 22.13 or later and is ESM-only"*). Next 14 only requires Node ≥ 18.17, so this raises
  the deployment's Node floor. The v8 line (8.0.4, 2024-11-12) has no `engines` constraint,
  and v9 *"reads v8 cookies"* both ways, so a rollback is available.
- **Revocation is the same gap as B, and the README says so directly:** `ttl: 0` *"means the
  seal never expires, which also means it can never be revoked: do not use `0` for
  authentication."* Even a non-zero `ttl` means logout is cookie-deletion only.

A browser refuses a cookie over 4096 bytes and *"iron-session throws rather than"* dropping
it silently; `chunk: true` splits across up to 4 cookies. Not a concern for
`{ id, email }`.

**Google Workspace swap — clean**, identically to B.

**Database fit.** Accounts table only. Knows nothing about your schema.

---

## D. Auth.js v5 (`next-auth@5.0.0-beta.32`) with the Credentials provider

**What it is.** A framework, not a session helper. You export `{ handlers, signIn, signOut,
auth }` from `NextAuth({...})` in `auth.ts`, mount `handlers` at a catch-all route, and read
the session server-side with `await auth()`. The Credentials provider is the escape hatch for
username/password: *"This provider is designed to forward any credentials inserted into the
login form … to your authentication service."* You supply an `authorize(credentials)` that
returns a user object or `null`.

**The thing to know before choosing it: Credentials does not get a database session.**

The v4 documentation states it outright: *"the Credentials provider can only be used if JSON
Web Tokens are enabled for sessions"* and *"users authenticated in this manner are not
persisted in the database"*
([next-auth.js.org/providers/credentials](https://next-auth.js.org/providers/credentials)).

The v5 Credentials page **no longer carries that sentence** — it says only *"By default, the
Credentials provider does not persist data in the database."* So I checked the source.
In `packages/core/src/lib/actions/callback/index.ts` on `main`, the `provider.type ===
"credentials"` branch ends unconditionally with:

```ts
const token = await callbacks.jwt({ token: defaultToken, user, account, isNewUser: false, trigger: "signIn" })
…
const newToken = await jwt.encode({ ...jwt, token, salt })
…
const sessionCookies = sessionStore.chunk(newToken, { expires: cookieExpires })
```

There is **no adapter branch** — no `createSession`, no session row. The behaviour is
unchanged in v5; only the documentation of it moved.

**Consequence for this ticket:** picking Auth.js + Credentials means picking the **stateless
cookie** (option B's properties) while *also* paying for a framework. Session strategy is
otherwise configurable — *"The default is `"jwt"` … If you use an `adapter` however, we
default it to `"database"` instead"*
([next-auth.js.org/configuration/options](https://next-auth.js.org/configuration/options)) —
but that door is closed for Credentials.

**Session carriage.** A JWE in the `authjs.session-token` cookie, chunked if large. Logout:
*"Auth.js deletes the JWT from the cookies, destroying the session"* — no server-side
revocation. Restart: fine if `AUTH_SECRET` is in the environment.

**Password hashing.** **None.** `authorize()` is your code; the docs' own example is a
comment, `// Your own logic for dealing with plaintext password strings; be careful!`, calling
a `saltAndHashPassword` you write. The docs list what else you own: *"you just have to
provide the necessary logic, eg. to encrypt passwords, add rate-limiting, add password reset
functionality, etc."*

**Google Workspace swap — the one with a trap.** Adding a `Google` provider does *not* by
default attach to the existing email/password account. Auth.js disables that: OAuth linking
requires `allowDangerousEmailAccountLinking`, and the reference says *"Automatic account
linking on sign in is not secure between arbitrary providers and is disabled by default."*
Without it, a CSM signing in through Workspace gets `OAuthAccountNotLinked` against the email
they already own. With it, you are enabling an option whose name contains the word
*Dangerous* — defensible here (one verified Google Workspace tenant, admin-seeded accounts,
no other provider) but it is a decision someone must make and record, not a default.

**Dependencies.** `next-auth@5.0.0-beta.32` → `@auth/core@0.41.3` (1.9 MB unpacked) →
`jose`, `oauth4webapi`, `@panva/hkdf`, **`preact@10.24.3` and `preact-render-to-string`** —
Preact is there to render the built-in sign-in pages this app would not use.

**Client bundle.** Server-side `auth()` keeps it off the client; but `signIn`/`signOut` from
`next-auth/react` and `SessionProvider` are client modules, and most published examples use
them. Reachable-but-avoidable.

**Database fit — poorest.** With Credentials there is no adapter, so Auth.js does not touch
the database at all: you write the account lookup yourself in `authorize()`. If you later
*add* the adapter (for Google), Auth.js brings **its own schema** (`users`, `accounts`,
`sessions`, `verification_tokens`), and that is a table set the #34 schema ticket has to
either adopt or fight.

**Variant: `next-auth@4.24.15` (stable).** Same Credentials/JWT constraint. App Router works
but via `getServerSession(authOptions)` rather than `auth()`. Choosing stability here costs
the ergonomics every current tutorial assumes.

---

## E. Better Auth 1.7.5

**What it is.** A full auth framework with first-class email/password, database sessions and
a schema it manages. You define `auth` once, mount `export const { GET, POST } =
toNextJsHandler(auth)` at `app/api/auth/[...all]/route.ts`, and read the session with
`auth.api.getSession({ headers: await headers() })`.

`peerDependencies.next` is `^14.0.0 || ^15.0.0 || ^16.0.0` (optional), so Next 14 is
supported.

**Session carriage — genuinely server-side.** *"The session is stored in a cookie and is sent
to the server on every request. The server then verifies the session and returns the user data
if the session is valid."* The `session` table holds `id`, `token`, `userId`, `expiresAt`,
`ipAddress`, `userAgent`; the cookie holds the `token`. Default lifetime 7 days (`expiresIn`),
refreshed when `updateAge` (default 1 day) is reached. Revocation is first-class:
`revokeSession()`, `revokeOtherSessions()`, `revokeSessions()`, and *"When a user signs out of
a device, the session is automatically ended."*
([Session Management](https://www.better-auth.com/docs/concepts/session-management))

An optional **cookie cache** puts session data in a short-lived signed cookie to skip the
database read — which reintroduces B's revocation lag for that window. It is off unless you
turn it on.

**Password hashing — provided.** *"Better Auth uses `scrypt` to hash passwords. The `scrypt`
algorithm is designed to be slow and memory-intensive to make it difficult for attackers to
brute force passwords."* Passwords live *"inside the `account` table with `providerId` set to
`credential`"*. Custom `hash`/`verify` can be supplied via `emailAndPassword.password`.
Default policy: 8–128 characters; email verification **not** required unless
`requireEmailVerification: true`.
([Email & Password](https://www.better-auth.com/docs/authentication/email-password))

**UNVERIFIED:** I did not find published scrypt cost parameters (N/r/p) for Better Auth's
default. Whether they meet OWASP's N = 2^17 minimum is not something I could confirm from the
docs; it would have to be read out of the source before anyone relies on it.

**Google Workspace swap — good, and the least code.** Add `socialProviders.google`. Better
Auth *"automatically links the OAuth account to that user"* when the email matches an existing
user and *"either the provider verified the email or it is in `trustedProviders`"* — Google
sets `email_verified`, so a joveo.com CSM who signed in with a password gets the same `user`
row when they later sign in with Workspace. `disableImplicitLinking` turns that off and
returns `account_not_linked` instead; `trustedProviders` carries the warning *"Use this with
caution as it may increase the risk of account takeover."*
([Users & Accounts](https://www.better-auth.com/docs/concepts/users-accounts))

Because the `user` row is preserved, threads keyed on `user.id` survive the swap. **This is
the only library option that preserves the #34 shape without a flag named "dangerous".**

**Database fit — the real cost.** Better Auth requires four tables — `user`, `session`,
`account`, `verification` — and it is opinionated about them. It offers `modelName` and
`fields` remapping (*"You can customize the table names and column names for the core schema
by using the `modelName` and `fields` properties"*) plus `additionalFields`, and
`npx @better-auth/cli migrate` will create or alter tables for the built-in Kysely adapter,
detecting Postgres `search_path`. But note what that means **in Brain's Neon instance**: an
auth library that issues DDL against the database that also holds `kb_pairs`. #34 already
flags that the Next app's credentials can reach Brain's tables unless grants say otherwise —
a library with a migration CLI makes that grants ticket a prerequisite rather than a
follow-up. ([Database](https://www.better-auth.com/docs/concepts/database))

**Dependencies — the largest by far.** `better-auth@1.7.5`, 2.0 MB unpacked, with ~15 direct
dependencies including `zod@^4`, `kysely`, `nanostores`, `@noble/hashes`, `@noble/ciphers`,
`jose`, `better-call`, and five bundled adapter packages (`@better-auth/kysely-adapter`,
`-prisma-adapter`, `-drizzle-adapter`, `-mongo-adapter`, `-memory-adapter`). For a repo whose
entire runtime dependency list is seven packages, this roughly doubles the tree.

**Client bundle.** `createAuthClient` from `better-auth/react` is the documented client path.
It is avoidable: the Next.js integration documents calling `signInEmail`/`signUpEmail` from a
**Server Action**, with the `nextCookies()` plugin added last so cookies actually get set —
*"When you call a function that needs to set cookies, like `signInEmail` or `signUpEmail` in a
server action, cookies won't be set … you can use the `nextCookies` plugin, which will
automatically set cookies for you."* That keeps the whole flow server-side, matching this
app's no-`NEXT_PUBLIC_*` posture.
([Next.js integration](https://www.better-auth.com/docs/integrations/next))

**Middleware caveat, stated by Better Auth itself.** For Next < 15.2, Edge middleware cannot
reach the database; the docs offer `getSessionCookie()` for an optimistic check and label it
**"THIS IS NOT SECURE!"**, adding *"You must always validate the session on your server for
any protected actions or pages."* This is the same Next 14 Edge constraint as everything else
here — it is not a Better Auth flaw, but it does mean the middleware shortcut in its docs is
not a route protection mechanism on this app's Next version.

---

## The Google Workspace swap, considered on its own

The #34 premise is: key the account on the `@joveo.com` email so the swap changes proof, not
identity. Research finds one wrinkle and one requirement.

**The wrinkle — Google says not to key on email.** Google's OpenID Connect documentation is
explicit: *"Don't use the `email` field as a unique identifier for a user. Always use the
`sub` field"*, because email *"may not be unique to this account and could change over time,
therefore you shouldn't use this value as the primary identifier to link to your user
record."*
([Google OpenID Connect docs](https://developers.google.com/identity/openid-connect/openid-connect))

This does **not** invalidate the #34 shape — it names its cost. Keying on email is what makes
the swap a no-op; the price is that if a CSM's address changes (a name change, a rebrand),
the row has to be re-pointed by an admin rather than following `sub` automatically. The
mitigation is to *store* `google_sub` on the account row when the swap happens and key on it
from then on, with email demoted to a lookup key for the one-time match. That keeps thread and
analytics rows untouched while retiring email as the identifier — worth writing into the spec
rather than discovering later.

**The requirement — check `hd`, and check it server-side.** Google: the `hd` claim is *"The
domain associated with the Google Workspace or Cloud organization of the user"*, and *"You
must check this claim when restricting access to a resource to only members of certain
domains. The absence of this claim indicates that the account does not belong to a Google
hosted domain."* The `hd` **request parameter** only optimises the account chooser: *"Don't
rely on this UI optimization to control who can access your app, as client-side requests can
be modified. Be sure to validate that the returned ID token has an `hd` claim value that
matches what you expect."* An `@joveo.com`-looking email on a consumer Google account is not
a Joveo employee.

Options A/B/C put that check in code you already wrote. D and E put it in a provider callback
(`signIn` / `profile` for Auth.js; a Better Auth hook) — **UNVERIFIED** in both cases: I did
not confirm from primary sources the exact callback shape for asserting `hd` in either
library, and it should not be written as if I had.

---

## What this rules out, and why

**Hosted identity providers (Clerk, Auth0, WorkOS, Stytch, Supabase Auth).** All are listed
by the Next 14 docs as compatible. All are ruled out by #34's premise: accounts live in
Brain's Neon instance, written by the Next app. A hosted IdP moves the account out of that
database, makes the `@joveo.com` email a foreign key into someone else's system, and turns
the Workspace swap into their migration rather than a callback you write. They would also put
a publishable key in the client — and this app has no `NEXT_PUBLIC_*` on purpose.

**Lucia, `oslo`, `@oslojs/*` as dependencies.** Lucia was deprecated in March 2025; `oslo`
last published 2024-06-26 and `@oslojs/crypto` 2024-09-21. Any 2024-vintage advice to "use
Lucia for sessions in the App Router" is dead. The *guidance* survives and is cited above.

**`bcrypt` / `bcryptjs`.** OWASP: bcrypt is for *"legacy systems"* only, and its 72-byte
input ceiling needs enforcing. There is no legacy hash corpus here to be compatible with —
accounts are being seeded fresh — so there is no reason to take the weaker option.

**Middleware as the place sessions are checked.** Next 14 middleware is Edge-only. Whatever
option wins, the real check happens in a Server Component, Route Handler or Server Action.
The Next 14 docs make this the headline point about authorization: *"While middleware can be
useful for initial validation, it should not be the sole line of defense in protecting your
data. The bulk of security checks should be performed in the Data Access Layer (DAL)."*

**A "session" table named `session`.** Out of scope for this file, but flagged: #34 puts both
*session* and *conversation* on `Thread`'s `_Avoid_` list in the glossary. Whichever option
wins, the login artefact needs a name that does not collide with a word the domain has
deliberately banned — and note that option E **names the table `session` by default** and can
only be renamed through `modelName`.

---

## Where the sources disagree with each other, or with their own version

| Claim you will meet | What's true here |
| --- | --- |
| "`const cookieStore = await cookies()`" | Next **15+**. In Next 14 `cookies()` is synchronous; async landed in `v15.0.0-RC` per the current docs' Version History. Awaiting a non-promise is harmless, so pasted 15-era code usually still runs — but `strict` TS will type it as a non-promise. |
| "Protect routes in `middleware.ts` by checking the session in the DB" | Needs Node middleware: **Next 15.2 experimental / Next 16**. Impossible on 14. |
| "Use `auth()` from `@/auth`" (Auth.js) | **v5 only**, which is `5.0.0-beta.32`. v4 stable uses `getServerSession(authOptions)`. |
| "Credentials + an adapter gives you database sessions" | False in v4 (documented) and in v5 (verified in `@auth/core` source on `main`). |
| "NextAuth is the default choice for Next.js" | `authjs.dev` now says *"The Auth.js project is now part of Better Auth"* and steers new projects to Better Auth. |
| The `lib/session.ts` + `lib/dal.ts` + `jose` + `bcrypt` tutorial pattern | That is the **Next 15/16** authentication guide. The Next 14 page is much thinner and names no library. The code works on 14; the citation doesn't. |

---

## Sources

Primary, all read 2026-09-15:

- Next.js 14.2.35 docs (archived at `/docs/14/`): [Authentication](https://nextjs.org/docs/14/app/building-your-application/authentication) (lastUpdated 2024-04-01), [`cookies`](https://nextjs.org/docs/14/app/api-reference/functions/cookies) (2024-03-18), [Middleware](https://nextjs.org/docs/14/app/building-your-application/routing/middleware) (2024-03-25), [Server Actions and Mutations](https://nextjs.org/docs/14/app/building-your-application/data-fetching/server-actions-and-mutations) (2024-03-30)
- Next.js 16.3.5 docs: [`cookies`](https://nextjs.org/docs/app/api-reference/functions/cookies) — for the async change only
- [Auth.js — Credentials](https://authjs.dev/getting-started/authentication/credentials), [Session strategies](https://authjs.dev/concepts/session-strategies), [provider reference](https://authjs.dev/reference/core/providers)
- [NextAuth v4 — Credentials provider](https://next-auth.js.org/providers/credentials), [Options](https://next-auth.js.org/configuration/options)
- `nextauthjs/next-auth`, `packages/core/src/lib/actions/callback/index.ts` on `main` — the credentials branch
- [Better Auth — Session Management](https://www.better-auth.com/docs/concepts/session-management), [Database](https://www.better-auth.com/docs/concepts/database), [Email & Password](https://www.better-auth.com/docs/authentication/email-password), [Users & Accounts](https://www.better-auth.com/docs/concepts/users-accounts), [Next.js integration](https://www.better-auth.com/docs/integrations/next)
- [Auth.js is now part of Better Auth](https://better-auth.com/blog/authjs-joins-better-auth) (2025-09-22); [Better Auth is joining Vercel](https://better-auth.com/blog/better-auth-joins-vercel) (2026-07-07)
- [lucia-auth.com](https://lucia-auth.com/) — deprecation notice
- [github.com/vvo/iron-session](https://github.com/vvo/iron-session) README on `main`
- [github.com/panva/jose](https://github.com/panva/jose) README
- [Node.js `crypto` docs](https://nodejs.org/api/crypto.html)
- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [The Copenhagen Book — Sessions](https://thecopenhagenbook.com/sessions)
- [Google Identity — OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect)
- npm registry metadata for `next-auth`, `@auth/core`, `better-auth`, `iron-session`, `jose`, `argon2`, `@node-rs/argon2`, `bcrypt`, `bcryptjs`, `oslo`, `@oslojs/crypto`, `next`

Repo, at `a6ff174`: `frontend/package.json`, `frontend/.env.example`,
`frontend/src/app/api/ask-naren/route.ts`, `frontend/src/app/ask-naren/page.tsx`,
`frontend/src/lib/thread.ts`, `CLAUDE.md`, and issues #34 / #35.
