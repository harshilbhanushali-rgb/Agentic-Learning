import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const refresh = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }));

import AskNarenError from './error';

describe('AskNarenError', () => {
  it('says the store is at fault, not the sign-in, and quotes the digest', () => {
    render(<AskNarenError error={Object.assign(new Error('x'), { digest: 'abc123' })} reset={vi.fn()} />);
    expect(screen.getByRole('heading', { name: 'Ask Naren can’t reach your threads' })).toBeInTheDocument();
    expect(screen.getByText(/you have not been signed out/)).toBeInTheDocument();
    expect(screen.getByText('Reference: abc123')).toBeInTheDocument();
  });

  it('shows no reference when there is no digest', () => {
    render(<AskNarenError error={new Error('x')} reset={vi.fn()} />);
    expect(screen.queryByText(/Reference:/)).not.toBeInTheDocument();
  });

  it('retries the server render as well as the boundary', async () => {
    const user = userEvent.setup();
    const reset = vi.fn();
    render(<AskNarenError error={new Error('x')} reset={reset} />);
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refresh).toHaveBeenCalledOnce();
    expect(reset).toHaveBeenCalledOnce();
  });
});
