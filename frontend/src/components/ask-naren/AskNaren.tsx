'use client';

import type { AskNarenDecline, AskNarenResponse } from '@/types';
import type { ThreadSummaryJson } from '@/lib/thread';

import { useCallback, useEffect, useRef, useState } from 'react';

import { SituationForm } from '@/components/ask-naren/SituationForm';
import { DeclineNotice } from '@/components/ask-naren/DeclineNotice';
import { ThreadRail } from '@/components/ask-naren/ThreadRail';
import { CoverageStarters } from '@/components/ask-naren/CoverageStarters';
import { HelpCard, isHelpCommand } from '@/components/ask-naren/HelpCard';
import { Asked, NotSavedNote, Outcome } from '@/components/ask-naren/Turn';
import { relativeTime } from '@/components/ask-naren/threadTime';
import { stashAndSignIn, takeStash } from '@/components/ask-naren/draftStash';
import * as api from '@/components/ask-naren/threadClient';
import { SignOutButton } from '@/components/auth/SignOutButton';
import { carriedScenario, scenarioLabel } from '@/lib/thread';

/**
 * Ask Naren (issue #3). One input; the response is answered, declined, clarify (#13) or
 * rendered (#19), and the conversation continues in a thread (#15) that is STORED ON THE
 * SERVER (#46) and listed in a rail beside the box (#39, variant A).
 *
 * NO `useMode()` CALL, DELIBERATELY. The page must render identically in Veteran and Newbie
 * mode, and not branching is the only implementation of that which cannot drift. Every
 * other page in the app branches; this one is the exception on purpose.
 *
 * SIGNED IN, ALWAYS (issue #44). `app/ask-naren/page.tsx` resolves the user and their rail on
 * the server and renders this only for someone signed in. A session can still end while the
 * page is open; that shows up as a 401 from a route, and the draft and the open thread are
 * stashed so signing back in returns to exactly that thread (ADR 0011).
 *
 * THE PAGE NO LONGER HOLDS THE THREAD. It sends `{situation, thread_id}`; the proxy route
 * loads the stored turns, derives the replay and records the new turn, and says in headers
 * which thread it went into. So nothing a browser holds can reach the service's prompt, and
 * a turn exists on screen only if it exists in storage -- with one marked exception: an
 * answer the store failed to record is shown, flagged "Not saved to this thread", and the
 * next question starts a fresh thread rather than replay one with a gap in it (#40).
 *
 * SIGN-IN LANDS ON AN EMPTY BOX (#39). The last thread is never reopened automatically; a
 * CSM picks one from the rail, or the stash reopens the one they were in when their session
 * ended.
 *
 * THERE IS STILL NO ERROR STATE FOR ANSWERS (issue #6). Every failure to answer arrives
 * decline-SHAPED and renders through DeclineNotice. Two of them are not turns: a store fault
 * (`store_unavailable`, #40) and the proxy itself not answering. Nothing was asked in either
 * case, so the question goes back in the box and the decline is shown once, above the
 * thread, rather than added to it.
 */

/** One turn on screen. `notSaved` marks the one kind of turn that is not in storage. */
interface TurnView {
  key: string;
  question: string;
  response: AskNarenResponse;
  askedAt: string;
  notSaved?: boolean;
}

/** The open thread. `threadId` null is a new thread, created by its first ask. `detached`:
 *  the last answer was not recorded, so the next question starts fresh (#40). */
interface Conversation {
  threadId: number | null;
  turns: TurnView[];
  detached: boolean;
}

const EMPTY: Conversation = { threadId: null, turns: [], detached: false };

export function AskNaren({
  user,
  initialThreads,
}: {
  user: { id: number; name: string };
  initialThreads: ThreadSummaryJson[];
}) {
  const [draft, setDraft] = useState('');
  const [threads, setThreads] = useState(initialThreads);
  const [railStale, setRailStale] = useState(false);
  const [conversation, setConversation] = useState<Conversation>(EMPTY);
  /** The question in flight, if any. */
  const [asking, setAsking] = useState<string | null>(null);
  /** The thread being fetched from the rail, if any. */
  const [opening, setOpening] = useState<number | null>(null);
  /** A decline that is not a turn: nothing was asked (store down, or the proxy gone). */
  const [flash, setFlash] = useState<AskNarenDecline | null>(null);
  /** One line about what just happened to a thread (removed, would not open, ...). */
  const [note, setNote] = useState<string | null>(null);
  /** The `/help` card is open. Not a turn: nothing was asked. */
  const [help, setHelp] = useState(false);
  /** Null until mounted: relative times are in the reader's zone, unknown to the server. */
  const [now, setNow] = useState<Date | null>(null);

  // Which view an in-flight request belongs to. A request takes ~12s, and "New thread" and
  // the rail are reachable throughout: without this, a resolving `ask` would paint its answer
  // into whatever thread the CSM has since moved to. The turn is still RECORDED in the thread
  // it was asked in -- the route did that -- so a stale answer only refreshes the rail.
  const generation = useRef(0);
  const nextKey = useRef(0);
  const draftRef = useRef(draft);
  draftRef.current = draft;

  useEffect(() => {
    setNow(new Date());
    const tick = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(tick);
  }, []);

  const refreshRail = useCallback(async () => {
    const r = await api.fetchThreads();
    if (r.kind === 'ok') {
      setThreads(r.value);
      setRailStale(false);
    } else if (r.kind !== 'signed_out') {
      setRailStale(true);
    }
  }, []);

  const signInAgain = useCallback(
    (threadId: number | null, pending = draftRef.current) =>
      stashAndSignIn(user.id, { draft: pending, threadId }),
    [user.id],
  );

  const openThread = useCallback(
    async (id: number) => {
      const gen = ++generation.current;
      setOpening(id);
      setAsking(null);
      setFlash(null);
      setNote(null);
      const r = await api.fetchThread(id);
      if (gen !== generation.current) return;
      setOpening(null);
      switch (r.kind) {
        case 'ok':
          setConversation({
            threadId: id,
            turns: r.value.turns.map(t => ({
              key: `s${id}-${t.position}`,
              question: t.question,
              response: t.response,
              askedAt: t.askedAt,
            })),
            detached: false,
          });
          return;
        case 'signed_out':
          signInAgain(id);
          return;
        case 'not_found':
          setConversation(EMPTY);
          setNote('That thread was removed from your list, so it could not be opened.');
          void refreshRail();
          return;
        case 'unavailable':
          setNote(
            'Ask Naren can’t reach your threads just now, so that thread did not open. ' +
              'This is a fault on our side — try again in a moment.',
          );
          return;
      }
    },
    [refreshRail, signInAgain],
  );

  // Back from a sign-in this page sent someone to (ADR 0011): the draft, and the thread it
  // was going into. A normal sign-in has no stash and lands on an empty box (#39).
  useEffect(() => {
    const stash = takeStash(user.id);
    if (!stash) return;
    if (stash.draft) setDraft(stash.draft);
    if (stash.threadId !== null) void openThread(stash.threadId);
  }, [user.id, openThread]);

  const newThread = () => {
    generation.current += 1;
    setConversation(EMPTY);
    setAsking(null);
    setOpening(null);
    setFlash(null);
    setNote(null);
  };

  const ask = async () => {
    const asked = draft.trim();
    if (!asked || asking !== null) return;
    if (isHelpCommand(asked)) {
      // Answered here, never sent: no search, no turn, nothing for the next question to
      // carry. The open thread is left exactly as it was.
      setDraft('');
      setHelp(true);
      return;
    }
    setHelp(false);
    // After an unsaved answer, the next question starts a new thread (#40).
    const from = conversation.detached ? EMPTY : conversation;
    if (conversation.detached) setConversation(EMPTY);
    const gen = generation.current;
    setAsking(asked);
    setDraft('');
    setFlash(null);
    setNote(null);

    const r = await api.ask(asked, from.threadId);
    if (r.kind === 'signed_out') {
      signInAgain(from.threadId, asked);
      return;
    }
    if (gen !== generation.current) {
      void refreshRail();
      return;
    }
    setAsking(null);

    switch (r.kind) {
      case 'thread_not_found':
        // Removed in another tab while this one had it open. Nothing was asked.
        setConversation(EMPTY);
        setDraft(asked);
        setNote(
          'That thread was removed from your list, so nothing was asked. Your question is ' +
            'back in the box — sending it starts a new thread.',
        );
        void refreshRail();
        return;
      case 'not_asked':
        setDraft(asked);
        setFlash(r.result);
        return;
      case 'answered': {
        const turn: TurnView = {
          key: `n${nextKey.current++}`,
          question: asked,
          response: r.result,
          askedAt: new Date().toISOString(),
          notSaved: !r.recorded,
        };
        setConversation({
          threadId: r.recorded ? r.threadId : from.threadId,
          turns: [...from.turns, turn],
          detached: !r.recorded,
        });
        void refreshRail();
        return;
      }
    }
  };

  const rename = async (id: number, title: string | null) => {
    const r = await api.renameThread(id, title);
    switch (r.kind) {
      case 'ok':
        setThreads(ts => ts.map(t => (t.id === id ? r.value : t)));
        return true;
      case 'signed_out':
        signInAgain(conversation.threadId);
        return false;
      case 'not_found':
        setNote('That thread was removed from your list.');
        void refreshRail();
        return false;
      case 'unavailable':
        setNote(
          'Could not rename that thread — Ask Naren can’t reach your threads just now. ' +
            'Try again in a moment.',
        );
        return false;
    }
  };

  const remove = async (id: number) => {
    const r = await api.removeThread(id);
    switch (r.kind) {
      case 'ok':
      case 'not_found':
        setThreads(ts => ts.filter(t => t.id !== id));
        if (conversation.threadId === id || opening === id) newThread();
        return true;
      case 'signed_out':
        signInAgain(conversation.threadId);
        return false;
      case 'unavailable':
        setNote(
          'Could not remove that thread — Ask Naren can’t reach your threads just now. ' +
            'Try again in a moment.',
        );
        return false;
    }
  };

  const { turns } = conversation;
  const continuing =
    conversation.threadId !== null && !conversation.detached && turns.length > 0 && opening === null;
  const scenario = continuing ? carriedScenario(turns) : '';
  const lastAsked = turns.length ? new Date(turns[turns.length - 1].askedAt) : null;
  const empty = threads.length === 0 && turns.length === 0 && asking === null && opening === null;

  return (
    // min-h matches workspace/ and simulator/: the app shell's sidebar is viewport-tall,
    // so a short page leaves it cut off above the fold.
    <div className="mx-auto grid min-h-[calc(100vh-var(--topbar-height))] max-w-[1080px] grid-cols-1 content-start gap-8 px-8 py-10 md:grid-cols-[240px_minmax(0,1fr)]">
      <ThreadRail
        threads={threads}
        activeId={opening ?? conversation.threadId}
        now={now}
        stale={railStale}
        onOpen={id => void openThread(id)}
        onNew={newThread}
        onRename={rename}
        onRemove={remove}
      />

      <div className="flex min-w-0 max-w-[720px] flex-col gap-8">
        <header className="flex flex-col gap-2">
          <h1 className="text-2xl font-bold tracking-[-0.01em] text-ink">Ask Naren</h1>
          <p className="text-sm leading-relaxed text-ink-2">
            Describe a live client situation. You get back the answer Naren gave when he faced
            the closest thing to it, with the call it came from.
          </p>
          <div className="flex items-center gap-2 text-[11px] text-ink-placeholder">
            <span>Signed in as {user.name}</span>
            <span aria-hidden="true">·</span>
            <SignOutButton />
          </div>
        </header>

        <div className="flex flex-col gap-3">
          {continuing && now && lastAsked && (
            // Visible on purpose (#39): a stale carried scenario is the known wrong-answer
            // risk, and only the CSM can tell that it is no longer their client's situation.
            <p className="border-l-2 border-accent pl-3 text-[12px] leading-relaxed text-ink-2">
              {scenario ? (
                <>
                  Continuing: <span className="font-semibold text-ink">{scenarioLabel(scenario)}</span>
                </>
              ) : (
                'Continuing this thread'
              )}
              , last asked {relativeTime(lastAsked, now)}.{' '}
              <span className="text-ink-placeholder">
                A different situation?{' '}
                <button
                  type="button"
                  onClick={newThread}
                  className="underline underline-offset-2 transition-colors duration-fast ease-out-quart hover:text-primary"
                >
                  Start a new thread
                </button>
                .
              </span>
            </p>
          )}
          {conversation.detached && (
            <p className="border-l-2 border-line pl-3 text-[12px] leading-relaxed text-ink-2">
              The last answer was not saved, so your next question starts a new thread.
            </p>
          )}
          {note && (
            <p role="status" className="border-l-2 border-line pl-3 text-[12px] leading-relaxed text-ink-2">
              {note}
            </p>
          )}
          <SituationForm value={draft} onChange={setDraft} onSubmit={ask} busy={asking !== null} />
        </div>

        {flash && <DeclineNotice result={flash} />}

        {help && <HelpCard onClose={() => setHelp(false)} />}

        {empty && !help && <CoverageStarters />}

        {opening !== null ? (
          <p className="flex items-center gap-3 text-[13px] text-ink-2" role="status">
            <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent" aria-hidden="true" />
            Opening thread&hellip;
          </p>
        ) : (
          (turns.length > 0 || asking !== null) && (
            <section className="flex flex-col gap-8" aria-live="polite" aria-busy={asking !== null}>
              {turns.map(turn => (
                <div key={turn.key} className="flex flex-col gap-4">
                  <Asked
                    message={turn.question}
                    when={now ? relativeTime(new Date(turn.askedAt), now) : undefined}
                  />
                  <Outcome result={turn.response} />
                  {turn.notSaved && <NotSavedNote />}
                </div>
              ))}

              {asking !== null && (
                <div className="flex flex-col gap-4">
                  <Asked message={asking} />
                  <div className="flex items-center gap-3 rounded-md border border-line-subtle bg-surface-raised px-6 py-5">
                    <span
                      className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent"
                      aria-hidden="true"
                    />
                    <span className="text-[13px] text-ink-2">
                      Searching Naren&rsquo;s calls for the closest exchange&hellip;
                    </span>
                  </div>
                </div>
              )}
            </section>
          )
        )}
      </div>
    </div>
  );
}
