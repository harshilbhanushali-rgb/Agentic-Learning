# 19. Any Joveo account may sign in, and joins as a member

Date: 2026-11-11. Status: accepted. Supersedes the "added by an admin, no self-signup" rule of ADR 0011 and ADR 0018. The rest of both stands.

## Context

Until now an admin had to add each person on `/admin` before they could sign in. Anyone else got "isn't set up for Ask Naren yet". The operator wants N10 open to everyone at Joveo without that step: sign in, start using it, and the admin adjusts roles afterwards.

## Decision

- **Any verified `@joveo.com` Google account may sign in.** Google already vouches for this. The callback checks `hd = joveo.com`, a verified email, and a token issued to this app for this attempt (`checkGoogleClaims`). Nothing about that check changes.
- **The first sign-in adds the person as a `member`.** The name is Google's own `name` claim, or, if Google sends none, one made from the email (`priya.shah@joveo.com` → "Priya Shah"). An admin can make them an admin on `/admin` as before.
- **Still refused:** a **disabled** user, and an email already linked to a **different** Google account. The insert is `on conflict (email) do nothing`, so an existing row is never changed by a sign-in. The refusal code `google_not_set_up` becomes `google_refused`, with copy saying their access is turned off.
- **Admins can still add people ahead of time.** A pre-added person is linked at their first sign-in, as before.
- **No grant change.** `ask_naren_app` already has `insert (email, name)` on `users` (ADR 0016) and `update (google_sub)`.

## Consequences

- **Who can use N10 is now "everyone at Joveo", and offboarding is "disable".** Removing access means disabling the person on `/admin`. Leaving Joveo also ends access, because Google stops vouching for the account.
- The user list grows with everyone who has ever tried the tool. The Usage page's "Signed in, never asked" count becomes the number of people who looked and didn't ask.
- **To undo it:** remove the insert from `authenticateGoogle` and restore the `google_not_set_up` copy. Users who joined this way stay as they are.
