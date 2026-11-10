# 18. Google is the only sign-in, and roles are set on /admin

Date: 2026-11-10. Status: accepted. Supersedes ADR 0017's "passwords stay on" and ADR 0016's "being an admin is not a database column". The rest of both stands.

## Context

ADR 0017 shipped Google sign-in with passwords kept underneath as a launch-week fallback. The operator then judged passwords redundant: everyone who uses N10 has a Joveo Google account, and a password form is a second way in to defend. They also wanted admins to make other people admins from `/admin`. Under ADR 0016 that needed a code change and a deploy, because admins were the built-in list plus the `ASK_NAREN_ADMIN_EMAILS` setting.

## Decision

- **Google is the only way to sign in.** The password form, the sign-in action, the password module, the reset button on `/admin`, and the CLI's password commands are deleted. Adding a person is now just an email and a name; they sign in with Google straight away.
- **Passwords are revoked at the database too.** `grants.sql` explicitly revokes `insert (password_hash)` and `update (password_hash)` from both roles. Deleting a grant line does not remove a grant already given. The column is kept and the stored hashes are cleared (set to null) once Google-only is live.
- **A role column**: `ask_naren.users.role`, either `member` (the default) or `admin`, from migration 0004. The role is read along with the session, so asking "is this person an admin?" needs no second query. A change takes effect on the person's next request.
- **The built-in admin stays** (`harshil.bhanushali@joveo.com`, in `admin-list.ts`). They are an admin whatever their role column says. The page will not change their role or disable them, and it will not let anyone change their own role or disable themselves. So `/admin` can never be left with nobody able to open it.
- **`ASK_NAREN_ADMIN_EMAILS` is no longer read.** Anyone listed there is made an admin on the page instead.
- **`ask_naren_app` gains `update (role)`**, and `ask_naren_admin` gains the same for the CLI's `role` command.

## Consequences

- **If Google sign-in breaks, nobody can sign in.** There is no fallback. Recovery is a fix and a deploy. The CLI still works against the database to manage users and roles, but it cannot sign anyone in.
- **What we gave up:** ADR 0016 kept "who is an admin" out of reach of the app's own login. Now that login can promote anyone. Someone who takes over the app, or steals an admin's session, can make an admin. That is a small step on from 0016, where the same login could already create users.
- Without the three Google settings, the login page says sign-in is not set up.
- **To undo the roles:** stop reading the column in `isAdmin` and the built-in list still works. **To bring passwords back:** restore the deleted code from git and the grants, then set a password for each person, because the old hashes are gone.
