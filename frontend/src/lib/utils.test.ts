import { describe, it, expect } from 'vitest';
import { cn } from './utils';

describe('cn', () => {
  it('joins class names', () => {
    expect(cn('a', 'b')).toBe('a b');
  });

  it('drops falsey entries', () => {
    expect(cn('a', false && 'b', undefined, null, 'c')).toBe('a c');
  });

  it('resolves conflicting Tailwind utilities in favour of the last', () => {
    expect(cn('px-2', 'px-4')).toBe('px-4');
  });
});
