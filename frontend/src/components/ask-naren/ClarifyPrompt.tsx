import type { AskNarenClarify } from '@/types';

/**
 * Ask Naren asking for something back rather than answering (issue #13 defines the shape;
 * issue #14 starts producing it).
 *
 * STYLED AS A QUESTION, NOT AS A FAILURE. A clarify is the tool working: it has decided,
 * before searching anything, that what it was given would retrieve badly -- most often a
 * paraphrase where the client's own words are what retrieval needs to see. Rendering it like
 * a decline would teach a CSM to read it as a dead end and give up, when the whole point is
 * that one more line of input gets them a real answer.
 *
 * `question` is printed as the service wrote it, for the same reason a decline's `message`
 * is: composing the sentence here would put the same explanation in two places, and the
 * service is the side that knows what it is missing.
 *
 * There is no answer, quote or citation to render, because the type has no such fields --
 * see the note on `AskNarenClarify`. Nothing was retrieved, so nothing is grounded, so
 * nothing here may look like an answer.
 */
export function ClarifyPrompt({ result }: { result: AskNarenClarify }) {
  return (
    <article className="flex flex-col gap-2 rounded-md border border-line bg-surface-raised p-6">
      <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-accent">
        One thing first
      </div>
      <p className="text-sm leading-relaxed text-ink">{result.question}</p>
      {/* Deliberately does NOT promise that Ask Naren remembers the earlier message.
          Clarify starts being emitted in #14 but threads only land in #15, so between them
          a reply is answered as a fresh situation. Copy that said "pick up where you left
          off" would be false for that whole window. Revisit once #15 ships. */}
      <p className="mt-1 text-[11px] text-ink-placeholder">
        Add that to your situation and ask again.
      </p>
    </article>
  );
}
