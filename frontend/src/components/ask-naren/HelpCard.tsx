/**
 * What `/help` shows: what Ask Naren can be asked, and how to ask it well. Static and local --
 * typing `/help` sends nothing to the service and is not a turn in the thread, so it costs no
 * search and cannot leak into the next question's context (issue #25 reads the thread).
 *
 * A SHORT VERSION OF `ask-naren/docs/what-ask-naren-answers.md`. The kinds of question are that
 * guide's groups A-E, the tips are its "How to ask well", and the last line is its "Honest
 * limits" in one sentence. If the guide changes what Ask Naren answers, change this with it.
 */
const ASK = [
  ['Reply to a client', '“client says our CPA doubled, what do I tell them?”'],
  ['Check your own reply', '“I told them we’d review it Friday — how would Naren handle it?”'],
  ['The general play', '“how do we usually handle MSA redlines?” then “what order?”, “how does he word it?”, “what goes wrong?”'],
  ['The real evidence', '“show me the actual exchange”, “what happened next?”, “which other clients raised this?”'],
  ['Call prep', '“renewal call with them Thursday, what should I be ready for?”'],
  ['What’s covered', '“what can you help with?”, “what comes up most?”'],
] as const;

const TIPS = [
  'Paste what the client actually said — that is what gets searched.',
  'Say what you want: a reply, the play, or a real example.',
  'Follow-ups can be short (“and if they push back?”). A different client is a new thread.',
  'Read the quote and the call it came from. If that call isn’t your situation, the answer isn’t either.',
] as const;

/** `onClose` absent: the card is part of an answer ("what do you cover"), not a panel the CSM
 *  opened, so it has nothing to close. */
export function HelpCard({ onClose }: { onClose?: () => void }) {
  return (
    <section
      aria-label="What Ask Naren can do"
      className="flex flex-col gap-4 rounded-2xl rounded-tl-md border border-line-subtle bg-bg shadow-sm px-6 py-5"
    >
      <div className="flex items-start justify-between gap-4">
        <p className="text-[13px] leading-relaxed text-ink-2">
          Ask Naren finds the closest moment in Naren&rsquo;s recorded calls and answers from what
          he actually said, with the quote and the call. If nothing is close, it says so.
        </p>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close help"
            className="shrink-0 text-[13px] leading-none text-ink-placeholder transition-colors duration-fast ease-out-quart hover:text-ink"
          >
            &times;
          </button>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
          What you can ask
        </h2>
        <ul className="flex flex-col gap-1.5">
          {ASK.map(([kind, example]) => (
            <li key={kind} className="text-[13px] leading-relaxed text-ink-2">
              <span className="font-medium text-ink">{kind}</span>
              <span className="text-ink-placeholder"> — {example}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-placeholder">
          For better answers
        </h2>
        <ul className="flex list-disc flex-col gap-1.5 pl-4">
          {TIPS.map(tip => (
            <li key={tip} className="text-[13px] leading-relaxed text-ink-2">
              {tip}
            </li>
          ))}
        </ul>
      </div>

      <p className="text-[11px] leading-relaxed text-ink-placeholder">
        Strongest on getting clients contracted, integrated and live. Thinner on rescuing a
        campaign that&rsquo;s already running, so expect more &ldquo;no grounded answer&rdquo; there.
      </p>
    </section>
  );
}

/** True for the `/help` command: the whole message, any case, surrounding spaces ignored. */
export function isHelpCommand(message: string): boolean {
  return message.trim().toLowerCase() === '/help';
}
