/**
 * Admin CLI for Ask Naren users (issue #44). `npm run users -- --help` for commands.
 * All logic lives in src/server/auth/admin-cli.ts; this file only wires it to a process.
 */
import { loadEnvConfig } from '@next/env';

import { USAGE, runCli } from '../src/server/auth/admin-cli';
import { adminDb } from '../src/server/db';

// The same .env.local the app reads, so the admin tool and the app cannot disagree about
// which database they are pointed at.
loadEnvConfig(process.cwd());

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString('utf8');
}

const argv = process.argv.slice(2);
if (!argv.length || argv.includes('--help')) {
  console.log(USAGE);
  process.exit(argv.length ? 0 : 2);
}
if (!process.env.ASK_NAREN_ADMIN_DATABASE_URL) {
  console.error('ASK_NAREN_ADMIN_DATABASE_URL is not set -- in the environment or .env.local.');
  process.exit(1);
}

runCli(argv, adminDb(), { out: line => console.log(line), readStdin })
  .then(code => process.exit(code))
  .catch(err => {
    console.error(err);
    process.exit(1);
  });
