import { describe, expect, it } from 'vitest';

import { plainAnswer } from './plainAnswer';

describe('plainAnswer', () => {
  it('drops the markers a reader never sees, and keeps lists readable', () => {
    const text = [
      '## What to tell them',
      'Joveo tracks **only** applicants who came through Joveo.',
      '',
      '- the pixel goes on the **thank-you** page',
      '- the ATS sends stages back',
      '---',
      '1. confirm the ATS',
      '2. share the pixel',
    ].join('\n');

    expect(plainAnswer(text)).toBe(
      [
        'What to tell them',
        'Joveo tracks only applicants who came through Joveo.',
        '• the pixel goes on the thank-you page\n• the ATS sends stages back',
        '1. confirm the ATS\n2. share the pixel',
      ].join('\n\n'),
    );
  });

  it('leaves plain prose as it is', () => {
    expect(plainAnswer('One line.\nSecond line.')).toBe('One line.\nSecond line.');
  });
});
