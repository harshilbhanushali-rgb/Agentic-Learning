// Pull every Ask Naren turn asked in a time window, as the APP role, into a JSON file.
// Reads the connection string from frontend/.env.local (never from the command line).
// Usage (from frontend/): node <this> <fromISO> <toISO> <outFile>
import { writeFileSync } from 'node:fs';
import { Resolver } from 'node:dns/promises';
import { createRequire } from 'node:module';
import { join } from 'node:path';
const require = createRequire(join(process.cwd(), 'package.json'));
const nextEnv = require('@next/env');
const pg = require('pg');

nextEnv.loadEnvConfig(process.cwd());
const [from, to, out] = process.argv.slice(2);
const url = new URL(process.env.ASK_NAREN_DATABASE_URL);

// This Mac's resolver (Tailscale) refuses *.neon.tech; resolve publicly, keep the name for SNI.
const resolver = new Resolver();
resolver.setServers(['8.8.8.8']);
const [ip] = await resolver.resolve4(url.hostname);

const client = new pg.Client({
  host: ip,
  port: Number(url.port || 5432),
  user: decodeURIComponent(url.username),
  password: decodeURIComponent(url.password),
  database: url.pathname.slice(1),
  ssl: { servername: url.hostname, rejectUnauthorized: true },
});
await client.connect();

const { rows } = await client.query(
  `select t.id as turn_id, t.thread_id, t.position, t.question, t.response, t.outcome, t.kind,
          t.reason, t.intent, t.scenario_key, t.cosine, t.asked_at, t.answered_at,
          th.title as thread_title, u.email, u.name
     from ask_naren.turns t
     join ask_naren.threads th on th.id = t.thread_id
     join ask_naren.users u on u.id = th.user_id
    where t.asked_at between $1 and $2
    order by t.asked_at`,
  [from, to],
);
await client.end();
writeFileSync(out, JSON.stringify(rows, null, 2));
const by = {};
for (const r of rows) by[r.email] = (by[r.email] ?? 0) + 1;
console.log(`${rows.length} turns`, by);
for (const r of rows)
  console.log(
    new Date(r.asked_at).toISOString().slice(11, 19),
    r.email.split('@')[0],
    `t${r.thread_id}#${r.position}`,
    r.outcome,
    r.intent ?? '',
    '|',
    r.question.replace(/\s+/g, ' ').slice(0, 110),
  );
