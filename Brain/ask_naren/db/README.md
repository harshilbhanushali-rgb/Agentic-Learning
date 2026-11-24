# Ask Naren on Postgres + pgvector (AWS RDS)

Since 2026-11-23, Ask Naren can run from one Postgres database on RDS in place of Neon
(Brain's tables) plus Pinecone (the vectors). This folder holds what that database needs.
It is synced into the deployment with the rest of `ask_naren/`, so the same files run from a
laptop or inside the deployed image.

## What lives where in the database

The database is **shared with another application**, which owns `public`. Nothing of ours
goes there.

| Schema | Holds | Created by |
|---|---|---|
| `extensions` | pgvector | `migrations/0001` |
| `brain` | Brain's tables (from `Brain/db/schema.sql`), `trigger_vectors`, `schema_migrations` | `0001`, `0002`, and `ops/copy_brain_to_rds.py` |
| `ask_naren` | users, sessions, threads, turns, feedback | `frontend/db/migrations` |

| Login | Used by | Can |
|---|---|---|
| master (`postgres`) | migrations and copies only, from a laptop | everything; **never give it to the app** |
| `ask_naren_service` | the Python service (`DATABASE_URL`) | SELECT six `brain` tables; every session read-only |
| `ask_naren_app` | the web app (`ASK_NAREN_DATABASE_URL`) | the `ask_naren` grants in `frontend/db/provision/grants.sql` |
| `ask_naren_admin` | the users CLI, optional | users and sessions only |

All three are SQL-created. RDS has no equivalent of Neon's Console roles to avoid, but the
master user is a member of `rds_superuser`, and the web app refuses to serve as one
(`frontend/src/server/privilege.ts`).

## Setting up a database

1. **Migrations and grants.** Put the master URL in `Brain/.env` as `ASK_NAREN_MIGRATE_URL`
   (never on a command line), then from `Brain/`:

   ```bash
   python -m ask_naren.db.migrate --also ask_naren=../frontend/db/migrations \
       --grants ../frontend/db/provision/roles.sql ../frontend/db/provision/grants.sql
   ```

   Or from the deployed image, with the variable in an env file:
   `docker run --rm --env-file .env <ask-naren image> python -m ask_naren.db.migrate`.
   Each file runs once; an edited, already-applied file stops the run. `--dry-run` lists
   what is pending and writes nothing.

2. **Passwords.** `ALTER ROLE <role> PASSWORD ...` for the three logins. RDS accepts a
   SCRAM-SHA-256 verifier, so the plaintext need never reach the server's logs. Keep the URLs
   in git-ignored env files only.

3. **Data.** From `Brain/`, on a laptop with the local embedding cache:

   ```bash
   python ops/copy_brain_to_rds.py brain --from DATABASE_URL_BRIDGE --label bridge-v3
   python ops/copy_brain_to_rds.py ask-naren --from DATABASE_URL_PRE_REBUILD
   ```

   Both take `--dry-run` and `--replace`. **Stop the app first and restart it after**: the
   copy refuses while the service (`brain`) or the web app (`ask-naren`) is connected, and a
   running service that finds its Brain replaced answers with an error until restarted,
   rather than quoting exchanges by ids that now mean something else. The vectors come from `Brain/gemini_embed_cache.db`,
   **never from Pinecone**: bulk vector reads there exhausted the account's monthly egress on
   2026-11-11 and took production search down. The copy writes
   `brain_meta.vector_store = pgvector`, which is what switches the service to this store.

4. **Check it.** Start the service with `DATABASE_URL` set to `ask_naren_service`'s URL and
   call `GET /verify`. It reports the login, read-only status, pgvector's version, table
   counts, vector width, that every answerable exchange has a vector, and that sampled
   vectors find themselves. HTTP 200 means every check passed; 503 names what failed.

## Connecting

RDS certificates are signed by Amazon's own authorities, which default trust stores lack.
`rds-global-bundle.pem` (public, from `truststore.pki.rds.amazonaws.com`) is that bundle.
`ask_naren.db.connection_url` upgrades every RDS URL to `sslmode=verify-full` against it.
The web app ships the same file at `db/certs/rds-global-bundle.pem` and names it in its URL:
`...?sslmode=verify-full&sslrootcert=<path to that file>`. Without it, node-postgres refuses
the connection (measured), which is the correct failure.

## Switching back

`DATABASE_URL` decides. Point it at a Neon Brain (which has no `vector_store` row) and the
service searches Pinecone exactly as before.

## Locally, without RDS

`docker-compose.yml` here runs `pgvector/pgvector:0.8.1-pg16` on `127.0.0.1:5433`, with no
password (trust login, reachable from this machine only). Point
`ASK_NAREN_PG_TEST_URL` at it to run the integration tests in
`tests/test_ask_naren_pgvector.py` (skipped when unset). Each test uses its own scratch
schema and drops it, so pointing them at staging is also safe.

## Measured on staging (2026-11-23)

A rehearsal with the pre-rebuild Brain (12,444 pairs, 6,496 answerable): the copy took about
two minutes from a laptop in India; `/verify` passed every check; one exact top-20 search over
the answerable vectors was about 100 ms of database time (`EXPLAIN ANALYZE`), plus a ~205 ms
round trip from that laptop. These are one-day planning figures, not a speed claim.
