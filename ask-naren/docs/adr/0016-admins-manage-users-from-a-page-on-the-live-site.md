# 16. Admins manage users from a page on the live site

Date: 2026-11-10. Status: accepted. Supersedes the "no admin UI" part of ADR 0011; the rest of 0011 stands.

## Context

ADR 0011 seeded users with a command-line tool and ruled out an admin page. ADR 0012 and `db/provision/grants.sql` made that a permission: the web app's role, `ask_naren_app`, can read users but cannot create one or set a password. Only `ask_naren_admin` can, and only the CLI held it. A compromised web app could not mint itself a sign-in.

With N10 going to Support and Implementation teams, adding people and resetting passwords from a terminal with a database credential is a bottleneck. The operator chose a page on the deployed site over a page that only works locally.

## Decision

- `/admin` on the live site: add a user, reset a password, disable or re-enable, and list everyone.
- Admins are the emails in `ASK_NAREN_ADMIN_EMAILS` (comma-separated). It is not a database column, so being an admin cannot be granted from the page. Unset means nobody is an admin. Anyone else gets a 404, so the page does not announce that it exists.
- ONE database credential. The app's own role, `ask_naren_app`, is granted `insert (email, name, password_hash)` and `update (password_hash, disabled_at)` on `ask_naren.users` (`grants.sql`). It still cannot change an email or name, delete a user, or reach Brain's tables, and the least-privilege check still runs. `ASK_NAREN_ADMIN_DATABASE_URL` is now optional: the CLI uses it when set and falls back to the app's login otherwise. (The operator chose one credential over a second admin login on the deployment.)
- Every server action checks the caller itself (`src/app/admin/actions.ts`), because a server action is a public endpoint regardless of which page it was written for.
- The page uses the same functions as the CLI (`src/server/auth/users.ts`), so both enforce the same rules: `@joveo.com` only, passwords of 12+ characters, a reset signs the user out everywhere, and disabling keeps their threads. An admin cannot disable themselves from the page.
- A password left empty is generated and shown once, as the CLI does.

## Consequences

- **What we gave up:** the app's own login can now create users and set passwords. Anyone who gains code execution in the app, steals its environment, or finds a SQL injection anywhere in it, can mint a sign-in. Before, they needed the separate admin credential as well. The blast radius is still the `ask_naren` schema only: Brain's tables stay unreachable.
- **A stolen admin session** can create users. Sessions keep their 14-day idle and 30-day absolute limits, and the admin list is short.
- The CLI keeps working, and remains the way to recover if the admin list is wrong.
- **To undo:** revoke the two new grants from `ask_naren_app` and use the CLI with the admin login. `/admin` then reports errors, and nothing else changes. Unsetting `ASK_NAREN_ADMIN_EMAILS` hides the page from everyone.
