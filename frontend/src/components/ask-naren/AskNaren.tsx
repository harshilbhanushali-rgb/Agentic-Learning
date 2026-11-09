'use client';

import type { AskNarenDecline, AskNarenResponse } from '@/types';
import type { ReactNode } from 'react';
import type { ThreadSummaryJson } from '@/lib/thread';

import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { N10Mark, PRODUCT_NAME } from '@/components/ask-naren/N10Mark';
import { SIDEBAR_SLOT_ID } from '@/components/sidebarSlot';
import { SituationForm } from '@/components/ask-naren/SituationForm';
import { DeclineNotice } from '@/components/ask-naren/DeclineNotice';
import { ThreadRail } from '@/components/ask-naren/ThreadRail';
import { CoverageStarters } from '@/components/ask-naren/CoverageStarters';
import { HelpCard, isHelpCommand } from '@/components/ask-naren/HelpCard';
import { Asked, NotSavedNote, Outcome } from '@/components/ask-naren/Turn';
import { relativeTime } from '@/components/ask-naren/threadTime';
import { stashAndSignIn, takeStash } from '@/components/ask-naren/draftStash';
import * as api from '@/components/ask-naren/threadClient';
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

  // The thread list lives in the app shell's sidebar (chat layout, 2026-11-10), portalled into
  // the slot the shell renders. `undefined` until mounted, so nothing jumps from the page into
  // the sidebar; `null` when there is no shell (tests render this alone), which shows it inline.
  const [slot, setSlot] = useState<HTMLElement | null | undefined>(undefined);
  useEffect(() => { setSlot(document.getElementById(SIDEBAR_SLOT_ID)); }, []);

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
  // Bring the newest thing into view, as a chat does: an answer, the "searching" line, the help
  // card or a notice. `scrollIntoView` is guarded because jsdom has none.
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' });
  }, [turns.length, asking, help, flash, opening]);
  const continuing =
    conversation.threadId !== null && !conversation.detached && turns.length > 0 && opening === null;
  const scenario = continuing ? carriedScenario(turns) : '';
  const lastAsked = turns.length ? new Date(turns[turns.length - 1].askedAt) : null;
  // The empty page: no turns on screen and nothing in flight, whether or not the CSM has
  // older threads in the sidebar. Sign-in lands here (#39).
  const home = turns.length === 0 && asking === null && opening === null;
  const firstName = user.name.trim().split(/\s+/)[0] ?? '';

  const rail = (
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
  );

  // Not turns: nothing was asked. Shown once, where the CSM is looking.
  const notices = (
    <>
      {help && <HelpCard onClose={() => setHelp(false)} />}
      {flash && <DeclineNotice result={flash} />}
    </>
  );

  return (
    // CHAT LAYOUT (2026-11-10, Vignesh: "close to Claude"): the thread list is in the sidebar;
    // an empty page is a centred greeting, box and starting points; a conversation reads top to
    // bottom with the newest reply last and the box pinned under it.
    <>
      {slot ? createPortal(rail, slot) : null}
      <div className="flex min-h-[calc(100vh-var(--topbar-height))] flex-col">
        {slot === null && <div className="mx-auto w-full max-w-[760px] px-6 pt-6">{rail}</div>}

        {home ? (
          <div className="mx-auto flex w-full max-w-[720px] flex-1 flex-col items-center justify-center gap-7 px-6 pb-14 pt-16">
            <div className="flex items-center gap-3.5">
              <N10Mark size={44} />
              <h1 className="text-balance text-[30px] font-bold leading-tight tracking-[-0.025em] text-ink">
                {firstName ? `Hey ${firstName}, what’s your question?` : 'What’s your question?'}
              </h1>
            </div>
            {note && (
              <p role="status" className="text-center text-[13px] leading-relaxed text-ink-2">
                {note}
              </p>
            )}
            <SituationForm large value={draft} onChange={setDraft} onSubmit={ask} busy={asking !== null} />
            {(help || flash) && <div className="flex w-full flex-col gap-4">{notices}</div>}
            {!help && <CoverageStarters onPick={setDraft} />}
            <p className="max-w-[620px] text-center text-[13px] leading-relaxed text-ink-2">
              {PRODUCT_NAME} answers from Naren&rsquo;s real client calls. Strongest on getting
              clients contracted, integrated and live; thinner on rescuing a campaign that&rsquo;s
              already running. When his calls don&rsquo;t cover something, it says so instead of
              guessing.
            </p>
          </div>
        ) : (
          <>
            <div className="mx-auto flex w-full max-w-[760px] flex-1 flex-col gap-6 px-6 py-8">
              {opening !== null ? (
                <p className="flex items-center gap-3 text-[14px] text-ink-2" role="status">
                  <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-primary" aria-hidden="true" />
                  Opening thread&hellip;
                </p>
              ) : (
                <section className="flex flex-col gap-8" aria-live="polite" aria-busy={asking !== null}>
                  {turns.map(turn => (
                    <div key={turn.key} className="flex flex-col gap-4">
                      <Asked
                        message={turn.question}
                        when={now ? relativeTime(new Date(turn.askedAt), now) : undefined}
                      />
                      <Reply>
                        <Outcome result={turn.response} />
                      </Reply>
                      {turn.notSaved && <NotSavedNote />}
                    </div>
                  ))}

                  {asking !== null && (
                    <div className="flex flex-col gap-4">
                      <Asked message={asking} />
                      <Reply>
                        <p className="flex items-center gap-3 pt-0.5 text-[15px] text-ink-2">
                          <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-primary" aria-hidden="true" />
                          Searching Naren&rsquo;s calls for the closest exchange&hellip;
                        </p>
                      </Reply>
                    </div>
                  )}
                </section>
              )}

              {notices}

              <div ref={bottom} aria-hidden="true" />
            </div>

            <div className="sticky bottom-0 mx-auto flex w-full max-w-[760px] flex-col gap-2 bg-surface px-6 pb-4 pt-2">
              {continuing && now && lastAsked && (
                // Visible on purpose (#39): a stale carried scenario is the known wrong-answer
                // risk, and only the CSM can tell that it is no longer their situation.
                <p className="px-2 text-[13px] leading-relaxed text-ink-2">
                  {scenario ? (
                    <>
                      Following up on <span className="font-semibold text-ink">{scenarioLabel(scenario)}</span>
                    </>
                  ) : (
                    'Following up in this thread'
                  )}
                  , last asked {relativeTime(lastAsked, now)}. A different scenario?{' '}
                  <button
                    type="button"
                    onClick={newThread}
                    className="font-semibold text-primary underline underline-offset-2 transition-colors duration-fast ease-out-quart hover:text-primary-hover"
                  >
                    Start a new question
                  </button>
                  .
                </p>
              )}
              {conversation.detached && (
                <p className="px-2 text-[13px] leading-relaxed text-ink-2">
                  The last answer was not saved, so your next question starts a new thread.
                </p>
              )}
              {note && (
                <p role="status" className="px-2 text-[13px] leading-relaxed text-ink-2">
                  {note}
                </p>
              )}
              <SituationForm value={draft} onChange={setDraft} onSubmit={ask} busy={asking !== null} />
            </div>
          </>
        )}
      </div>
    </>
  );
}

/** One reply from N10: the mark beside whatever came back, the way a chat shows who is talking. */
function Reply({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3.5">
      <span className="pt-1">
        <N10Mark size={26} />
      </span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
