# 17. Google sign-in is a hand-rolled code flow, beside passwords

Date: 2026-11-10. Status: accepted. Carries out "The Google Workspace swap" in ADR 0011, with one change: passwords stay on for now.

## Context

ADR 0011 decided what a Google sign-in *is*: Google proves the identity, the first sign-in matches the seeded user by email, requires `hd = joveo.com` and a verified email, and stores Google's `sub`; after that the match is on `sub`. A Google identity with no seeded user is refused. The schema has carried a nullable, unique `google_sub` since migration 0001. This ADR records how it was built, for the N10 launch.

## Decision

- **The OpenID Connect authorization-code flow, by hand, with no new dependency**, for ADR 0011's reasons. It is two route handlers (`/api/auth/google/start`, `/api/auth/google/callback`) and `src/server/auth/google.ts`.
- **One attempt is a short cookie**: `state`, `nonce`, a PKCE verifier and where to land afterwards. It lasts 10 minutes and is used once. It is `HttpOnly; SameSite=Lax` (Strict would be dropped on Google's cross-site redirect back). In production its name has the `__Host-` prefix, so no other `*.joveo.com` site can plant one, which would otherwise allow a login-CSRF. The state is checked before Google is asked anything.
- **The ID token's signature is not checked.** It comes straight from Google's token endpoint over TLS, in answer to a request carrying our client secret, which proves the issuer (OpenID Connect Core 3.1.3.7; Google's OIDC guide says the same). What is checked: issuer, audience (our client id), expiry, nonce, `hd = joveo.com`, `email_verified`, and a `@joveo.com` email. This avoids fetching and caching Google's signing keys.
- **The `hd` URL parameter is only a hint** to Google's account picker. The check is `hd` inside the token.
- **A Google sign-in ends in the same session as a password does.** Same row, same cookie, same lifetimes. So the session check and the admin check (`ASK_NAREN_ADMIN_EMAILS`, ADR 0016) cannot tell the two apart.
- **Passwords stay on, beneath the Google button.** This departs from ADR 0011's "after cutover, password sign-in is switched off". It is a launch-week fallback in case the Google client misbehaves, and the CLI and `/admin` still set passwords. Turning passwords off later is a separate step: clear the hashes and remove the form.
- **The redirect URI is configured** (`ASK_NAREN_GOOGLE_REDIRECT_URI`), not taken from the request. Behind the deployment's proxy the request's own host is not the public one Google knows.
- **Grants**: `ask_naren_app` gains `update (google_sub)` on `ask_naren.users`, and nothing else. `grants.sql` must be re-run on the database.

## Consequences

- The deployment needs outbound HTTPS to `oauth2.googleapis.com`, and three settings (`.env.example`). Without all three, Google sign-in is simply absent.
- If a user's email is renamed in Workspace, sign-in keeps working, because the match is on `sub`. Their email in `users` does not follow the rename.
- An email already linked to one Google identity refuses a different one. If a person's Google account is ever recreated, an admin has to clear `google_sub` by hand. There is no UI for that.
- While both methods are on, a leaked password still signs someone in. That risk goes away when passwords are switched off.
