import { describe, expect, it } from 'vitest';

import { boldSpans } from './boldSpans';

describe('boldSpans', () => {
  it('bolds **pairs** and keeps the text around them', () => {
    expect(boldSpans('1. **Delineate Responsibilities**: separate client setup.')).toEqual([
      { text: '1. ', bold: false },
      { text: 'Delineate Responsibilities', bold: true },
      { text: ': separate client setup.', bold: false },
    ]);
  });

  it('handles several on separate lines, as the answerer writes them', () => {
    const spans = boldSpans('Steps:\n1. **One**: a\n2. **Two**: b');
    expect(spans.filter(s => s.bold).map(s => s.text)).toEqual(['One', 'Two']);
    expect(spans.map(s => s.text).join('')).toBe('Steps:\n1. One: a\n2. Two: b');
  });

  it('leaves plain text, a lone **, and "** spaced **" alone', () => {
    expect(boldSpans('no markup')).toEqual([{ text: 'no markup', bold: false }]);
    expect(boldSpans('a ** b')).toEqual([{ text: 'a ** b', bold: false }]);
    expect(boldSpans('x ** not bold ** y')).toEqual([{ text: 'x ** not bold ** y', bold: false }]);
  });

  it('never turns anything else into markup', () => {
    const spans = boldSpans('<b>html</b> [link](http://x) # heading');
    expect(spans).toEqual([{ text: '<b>html</b> [link](http://x) # heading', bold: false }]);
  });
});
