import { redirect } from 'next/navigation';

// Ask Naren is the only live page; the rest are archived under src/app/_archive/.
export default function Home() {
  redirect('/ask-naren');
}
