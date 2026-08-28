import { ChatEngine } from '@/components/chat/ChatEngine';

/* The page contributes only the frame. Everything inside is ChatEngine,
 * which is container-agnostic so it can also back the ⌘K panel later. */

export const metadata = { title: 'Oracle · Joveo CS Platform' };

export default function ChatPage() {
  return (
    <div className="h-[calc(100vh-var(--topbar-height))]">
      <ChatEngine />
    </div>
  );
}
