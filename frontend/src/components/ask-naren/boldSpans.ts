/**
 * The one piece of markdown an answer is allowed to carry: `**bold**`.
 *
 * The answerer writes step names in bold ("1. **Delineate …**: …"), and the card rendered
 * them as literal asterisks. This is deliberately not a markdown renderer: headings, links,
 * lists and raw HTML stay plain text, so nothing a model writes can change the page's
 * structure or inject markup -- React escapes every span. Numbered lines already read
 * correctly under `whitespace-pre-line`.
 *
 * An unmatched `**` is left as written rather than bolding the rest of the answer.
 */
export function boldSpans(text: string): { text: string; bold: boolean }[] {
  const out: { text: string; bold: boolean }[] = [];
  const pattern = /\*\*(?=\S)([\s\S]*?\S)\*\*/g;
  let last = 0;
  for (let m = pattern.exec(text); m; m = pattern.exec(text)) {
    if (m.index > last) out.push({ text: text.slice(last, m.index), bold: false });
    out.push({ text: m[1], bold: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), bold: false });
  return out;
}
