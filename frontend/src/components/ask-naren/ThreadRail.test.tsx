import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { ThreadSummaryJson } from '@/lib/thread';

import { ThreadRail } from './ThreadRail';

const NOW = new Date(2026, 8, 28, 12, 0, 0);

function thread(over: Partial<ThreadSummaryJson> = {}): ThreadSummaryJson {
  const at = new Date(NOW.getTime() - 2 * 60 * 60_000).toISOString();
  return { id: 1, title: 'Applies are flat', renamed: false, createdAt: at, lastTurnAt: at, turnCount: 3, ...over };
}

function renderRail(props: Partial<Parameters<typeof ThreadRail>[0]> = {}) {
  const handlers = {
    onOpen: vi.fn(),
    onNew: vi.fn(),
    onRename: vi.fn(async () => true),
    onRemove: vi.fn(async () => true),
  };
  render(
    <ThreadRail threads={[thread()]} activeId={null} now={NOW} stale={false} {...handlers} {...props} />,
  );
  return handlers;
}

describe('ThreadRail', () => {
  it('always offers New thread', async () => {
    const user = userEvent.setup();
    const { onNew } = renderRail({ threads: [] });
    await user.click(screen.getByRole('button', { name: /New thread/ }));
    expect(onNew).toHaveBeenCalledOnce();
    expect(screen.getByText(/No threads yet/)).toBeInTheDocument();
  });

  it('groups by calendar day in the reader’s zone, with a count and a relative time', () => {
    const day = 86_400_000;
    renderRail({
      threads: [
        thread({ id: 1, title: 'today one', turnCount: 1 }),
        thread({ id: 2, title: 'yesterday one', lastTurnAt: new Date(NOW.getTime() - day).toISOString() }),
        thread({ id: 3, title: 'old one', lastTurnAt: new Date(NOW.getTime() - 60 * day).toISOString() }),
      ],
    });
    const headings = screen.getAllByRole('heading').map(h => h.textContent);
    expect(headings).toEqual(['Today', 'Yesterday', 'Earlier']);
    expect(screen.getByText('1 turn · 2 hours ago')).toBeInTheDocument();
    expect(screen.getByText('3 turns · yesterday')).toBeInTheDocument();
  });

  /* The server render does not know the reader's zone, so the list waits for mount rather
   * than print groups the browser would immediately contradict. */
  it('holds the list back until there is a client clock', () => {
    renderRail({ now: null });
    expect(screen.queryByText('Applies are flat')).not.toBeInTheDocument();
  });

  it('marks the open thread and opens one on click', async () => {
    const user = userEvent.setup();
    const { onOpen } = renderRail({ activeId: 1 });
    const open = screen.getByRole('button', { name: /^Applies are flat/ });
    expect(open).toHaveAttribute('aria-current', 'true');
    await user.click(open);
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it('says when the list may be behind', () => {
    renderRail({ stale: true });
    expect(screen.getByText(/may be out of date/)).toBeInTheDocument();
  });
});

describe('ThreadRail rename', () => {
  async function startRename(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole('button', { name: 'Rename “Applies are flat”' }));
    return screen.getByLabelText('Thread title') as HTMLInputElement;
  }

  it('focuses the field with the title selected, and Enter saves the trimmed title', async () => {
    const user = userEvent.setup();
    const { onRename } = renderRail();
    const field = await startRename(user);
    expect(field).toHaveFocus();
    expect(field.selectionStart).toBe(0);
    expect(field.selectionEnd).toBe('Applies are flat'.length);

    await user.clear(field);
    await user.type(field, '  Acme pause  {Enter}');
    expect(onRename).toHaveBeenCalledWith(1, 'Acme pause');
    // Back to the title either way; the page decides what the title now is.
    await waitFor(() => expect(screen.queryByLabelText('Thread title')).not.toBeInTheDocument());
  });

  it('an emptied title clears the rename back to the first question', async () => {
    const user = userEvent.setup();
    const { onRename } = renderRail();
    const field = await startRename(user);
    await user.clear(field);
    await user.keyboard('{Enter}');
    expect(onRename).toHaveBeenCalledWith(1, null);
  });

  it('an unchanged title saves nothing', async () => {
    const user = userEvent.setup();
    const { onRename } = renderRail();
    await startRename(user);
    await user.keyboard('{Enter}');
    expect(onRename).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('Thread title')).not.toBeInTheDocument();
  });

  it('Escape cancels, and the blur that follows does not save', async () => {
    const user = userEvent.setup();
    const { onRename } = renderRail();
    const field = await startRename(user);
    await user.type(field, 'x');
    fireEvent.keyDown(field, { key: 'Escape' });
    fireEvent.blur(field);
    expect(onRename).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('Thread title')).not.toBeInTheDocument();
  });

  it('blur saves, once', async () => {
    const user = userEvent.setup();
    const { onRename } = renderRail();
    const field = await startRename(user);
    await user.clear(field);
    await user.type(field, 'x');
    fireEvent.blur(field);
    fireEvent.blur(field);
    expect(onRename).toHaveBeenCalledTimes(1);
    expect(onRename).toHaveBeenCalledWith(1, 'x');
    await waitFor(() => expect(screen.queryByLabelText('Thread title')).not.toBeInTheDocument());
  });

  it('other keys just type', async () => {
    const user = userEvent.setup();
    const { onRename } = renderRail();
    const field = await startRename(user);
    await user.clear(field);
    await user.type(field, 'ab');
    expect(field).toHaveValue('ab');
    expect(onRename).not.toHaveBeenCalled();
  });
});

describe('ThreadRail remove', () => {
  it('asks first, and Keep it backs out', async () => {
    const user = userEvent.setup();
    const { onRemove } = renderRail();
    await user.click(screen.getByRole('button', { name: 'Remove “Applies are flat” from your list' }));
    const confirm = screen.getByRole('group', { name: 'Confirm removal' });
    expect(confirm).toHaveTextContent('You will not be able to open it again.');

    await user.click(within(confirm).getByRole('button', { name: 'Keep it' }));
    expect(onRemove).not.toHaveBeenCalled();
    expect(screen.queryByRole('group', { name: 'Confirm removal' })).not.toBeInTheDocument();
  });

  it('returns to the row when the remove did not happen', async () => {
    const user = userEvent.setup();
    const onRemove = vi.fn(async () => false);
    renderRail({ onRemove });
    await user.click(screen.getByRole('button', { name: 'Remove “Applies are flat” from your list' }));
    await user.click(screen.getByRole('button', { name: 'Remove from your list' }));
    expect(onRemove).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole('group', { name: 'Confirm removal' })).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: /^Applies are flat/ })).toBeInTheDocument();
  });

  it('stays on the confirmation while the list drops the removed row', async () => {
    const user = userEvent.setup();
    const onRemove = vi.fn(async () => true);
    renderRail({ onRemove });
    await user.click(screen.getByRole('button', { name: 'Remove “Applies are flat” from your list' }));
    await user.click(screen.getByRole('button', { name: 'Remove from your list' }));
    expect(onRemove).toHaveBeenCalledOnce();
    expect(screen.getByRole('group', { name: 'Confirm removal' })).toBeInTheDocument();
  });
});
