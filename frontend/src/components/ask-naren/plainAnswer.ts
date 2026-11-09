import { answerBlocks } from './answerBlocks';
import { boldSpans } from './boldSpans';

/**
 * An answer as plain text for the clipboard: what a CSM pastes into an email or a ticket.
 * Built from the same block grammar the card renders, so what is copied is what was read --
 * `**bold**` and `## ` markers are dropped rather than pasted as stray symbols, lists keep
 * their bullets and numbers, and blocks are separated by a blank line.
 */
export function plainAnswer(text: string): string {
  const inline = (s: string) => boldSpans(s).map(span => span.text).join('');
  return answerBlocks(text)
    .map(block => {
      switch (block.kind) {
        case 'heading':
        case 'paragraph':
          return inline(block.text);
        case 'bullets':
          return block.items.map(item => `• ${inline(item)}`).join('\n');
        case 'numbered':
          return block.items.map((item, i) => `${i + 1}. ${inline(item)}`).join('\n');
        case 'rule':
          return '';
      }
    })
    .filter(Boolean)
    .join('\n\n');
}
