import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import OriginButtonPreview, { OriginButtonPreview as Named } from './origin-button-demo';

/* Archived with the pages it went with; kept rendering so restoring it is a move, not a
 * repair. The primitive it wraps (src/components/ui/) is coverage-excluded -- see
 * vitest.config.ts. */
describe('OriginButtonPreview', () => {
  it('renders the Origin button, as the default and the named export', () => {
    expect(Named).toBe(OriginButtonPreview);
    render(<OriginButtonPreview />);
    expect(screen.getByRole('button', { name: 'Origin Button' })).toBeInTheDocument();
  });
});
