/**
 * The small block grammar a composed answer is written in: `## ` / `### ` headings, `- ` or
 * `* ` bullets, `1. ` numbered items, `---` rules, and paragraphs. Inline, only `**bold**`
 * (see `boldSpans`).
 *
 * Deliberately not a markdown renderer: it parses into plain data, the card renders that as
 * React elements, and React escapes every string -- so nothing a model writes can inject
 * markup or links. Anything outside the grammar is shown as the text it is.
 */
export type AnswerBlock =
  | { kind: 'heading'; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'bullets'; items: string[] }
  | { kind: 'numbered'; items: string[] }
  | { kind: 'rule' };

const HEADING = /^#{1,4}\s+(.*)$/;
const BULLET = /^[-*•]\s+(.*)$/;
const NUMBERED = /^\d+[.)]\s+(.*)$/;
const RULE = /^(-{3,}|\*{3,}|_{3,})$/;

export function answerBlocks(text: string): AnswerBlock[] {
  const blocks: AnswerBlock[] = [];
  let paragraph: string[] = [];

  const flush = () => {
    if (paragraph.length) blocks.push({ kind: 'paragraph', text: paragraph.join('\n') });
    paragraph = [];
  };
  const listItem = (kind: 'bullets' | 'numbered', item: string) => {
    flush();
    const last = blocks[blocks.length - 1];
    if (last && last.kind === kind) last.items.push(item);
    else blocks.push({ kind, items: [item] });
  };

  for (const raw of text.split('\n')) {
    const line = raw.trim();
    let m: RegExpMatchArray | null;
    if (!line) flush();
    else if (RULE.test(line)) { flush(); blocks.push({ kind: 'rule' }); }
    else if ((m = line.match(HEADING))) { flush(); blocks.push({ kind: 'heading', text: m[1] }); }
    else if ((m = line.match(BULLET))) listItem('bullets', m[1]);
    else if ((m = line.match(NUMBERED))) listItem('numbered', m[1]);
    else paragraph.push(line);
  }
  flush();
  return blocks;
}
