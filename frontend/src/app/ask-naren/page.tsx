import { AskNaren } from '@/components/ask-naren/AskNaren';
import { requireUser } from '@/server/auth/current-user';

/**
 * Ask Naren requires a signed-in user (issue #44). This wrapper exists so the check happens
 * on the server, before anything renders -- the page body is a client component and cannot
 * read a session itself. The only page that is gated: it is the only one serving real data
 * (Naren's calls, client names), and the only one whose threads have an owner.
 */
export default async function AskNarenPage() {
  const user = await requireUser('/ask-naren');
  return <AskNaren user={{ id: user.id, name: user.name }} />;
}
