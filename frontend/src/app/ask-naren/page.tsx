import { AskNaren } from '@/components/ask-naren/AskNaren';
import { requireUser } from '@/server/auth/current-user';
import { db } from '@/server/db';
import { listThreads } from '@/server/threads';
import { summaryJson } from '@/lib/thread';

/**
 * Ask Naren requires a signed-in user (issue #44). This wrapper exists so the check happens
 * on the server, before anything renders -- the page body is a client component and cannot
 * read a session itself. The only page that is gated: it is the only one serving real data
 * (Naren's calls, client names), and the only one whose threads have an owner.
 *
 * The rail arrives with the page (#39) -- this user's threads only, newest first -- and no
 * thread is opened: sign-in lands on an empty box. A store fault in either read throws, and
 * `error.tsx` beside this file says so in the tool's own words (#40).
 */
export default async function AskNarenPage() {
  const user = await requireUser('/ask-naren');
  const threads = await listThreads(db(), user.id);
  return <AskNaren user={{ id: user.id, name: user.name }} initialThreads={threads.map(summaryJson)} />;
}
