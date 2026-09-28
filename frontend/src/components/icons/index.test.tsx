import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { createElement } from 'react';
import type { ReactElement } from 'react';
import * as icons from './index';

/**
 * Every export in this module is a zero-prop inline SVG. There is no behaviour to
 * assert beyond "it renders an <svg>", so this iterates the module namespace rather
 * than naming 27 components by hand -- which also means an icon added later is covered
 * the moment it is exported, instead of quietly dropping the file's coverage.
 */
describe('icons', () => {
  const entries = Object.entries(icons) as [string, () => ReactElement][];

  it('exports every icon as a component', () => {
    expect(entries.length).toBeGreaterThan(20);
    for (const [name, Icon] of entries) {
      expect(typeof Icon, `${name} should be a component`).toBe('function');
    }
  });

  it.each(entries)('%s renders an svg', (_name, Icon) => {
    const { container } = render(createElement(Icon));
    expect(container.querySelector('svg')).toBeInTheDocument();
  });
});
