# Sessions are hand-rolled rows, not an auth library

Ask Naren is gaining **users** and server-stored threads (map #34). A reader who finds a hand-rolled session — our own token, our own table, our own cookie handling — will assume nobody looked at the libraries. We looked at five options (#35) and chose to write it ourselves (#36). This records why.

We decided that **a session is an opaque random token in an `HttpOnly; Secure; SameSite=Lax` cookie, backed by a `session` row we own**, keyed on the token's SHA-256 so that a read of the table cannot be replayed as live logins. Passwords are hashed with `node:crypto` scrypt at OWASP's minimum (N=2^17, r=8, p=1, `maxmem` raised past Node's default). No auth dependency is added.

## Why a row, not a stateless cookie

Signing out has to take effect on the server immediately. Users are admin-seeded, so the mirror image of seeding — **offboarding** someone who has left — is an admin action, and a stateless cookie (a JWT via `jose`, `iron-session`, Auth.js Credentials) cannot be cut off before it expires without a blocklist table, which is this design with extra steps. The usual argument for stateless — no database read per request — is already spent: #42 put the session check in a data-access layer next to the data, and every page that checks a session goes on to read threads from the same database.

## Why not Better Auth

Better Auth was the only library that also keeps a server-side session row, and it lost on three counts:

- **Its migration CLI issues DDL against Brain's Neon instance**, which would make the grants question (#38) a prerequisite for choosing a login mechanism, and put a third party's schema decisions into the instance whose pipeline Ask Naren is built never to write to.
- **Its core schema has a table named `account`** (a provider/credential link). `account` already means a Joveo client in this codebase (`ask-naren/CONTEXT.md`, **Where else seen**), and #36 named the sign-in record **user** specifically to keep it that way. A library table would bring back a third meaning unless remapped.
- **About fifteen direct dependencies** in an app that has seven runtime dependencies in total, to buy code that for us is ~150–250 lines.

Auth.js v5 was excluded earlier: Credentials cannot use a database session, and it has been in beta for two years. Lucia, the reference for hand-rolled sessions, is deprecated in favour of exactly this approach.

## What else was fixed with it

- **Lifetime**: 14 days idle, 30 days absolute. On expiry mid-thread the CSM signs in and returns to the same thread with the unsent draft kept; the thread itself is on the server and loses nothing.
- **Sign out** ends this browser's session. An admin can end all of a user's sessions. **Offboarding is disabling the user *and* deleting their sessions** — deleting sessions alone lets them sign straight back in, and deleting the user would take their threads and the analytics rows with them.
- **Passwords are set by an admin**, via a Node script that shares the login path's hashing code, and handed to the user directly. There is no temporary password, no forced change and no self-service reset: a reset is the admin setting a new one.
- **No throttling on sign-in.** The app relies on a network boundary. **Exposing it publicly reopens this ADR.**
- **Secrets**: the only credential this design needs is the Postgres connection string, which thread storage needs anyway. It is a runtime environment variable for now, never `NEXT_PUBLIC_*`. The production secret store belongs to the deployment effort.

## The Google Workspace swap, decided now

Workspace changes how identity is *proved*, not what it *is*. The first Google sign-in matches the existing user **by email**, requires `hd = joveo.com` and `email_verified`, and stores Google's `sub`. After that the match is on `sub`, because Google says not to treat email as a permanent identifier. A Google identity with no seeded user is **refused**, never created. After cutover, password sign-in is switched off and the hashes are cleared. So `password_hash` is nullable and `google_sub` is a nullable unique column from day one, and the swap needs no schema migration.

## Consequences

- We own security-sensitive code. It is small, but it gets a review before merge on the points that fail silently: token entropy, constant-time comparison, cookie flags, scrypt parameters.
- The session check is a database read, so **when the store is down, nobody can be recognised as signed in** — there is no stateless fallback. What the CSM sees then is #40's decision.
