import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { CaseStudyCard } from './CaseStudyCard';
import { CaseStudyModal } from './CaseStudyModal';
import { FailureModal } from './FailureModal';
import { FailureCard } from './FailureCard';
import { ModuleCard } from './ModuleCard';
import { SpotlightCard } from './SpotlightCard';
import { CourseSection } from './CourseSection';
import { CoursesTab } from './CoursesTab';
import { FailureLibraryTab } from './FailureLibraryTab';
import { CaseStudiesTab } from './CaseStudiesTab';
import { caseStudy, failureEntry } from '../../../tests/fixtures/domain';
import { SPOTLIGHT, COURSE_SECTIONS, CASE_STUDIES } from '@/data/library';

describe('CaseStudyCard', () => {
  it('reports chapter progress and calls back on open', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const cs = caseStudy({ total: 12, chapters: [{ num: 1, title: 'A', summary: 'a' }] });

    render(<CaseStudyCard cs={cs} onOpen={onOpen} />);
    expect(screen.getByText(/Chapters . 1 of 12 . Live/)).toBeInTheDocument();

    await user.click(screen.getByRole('button'));
    expect(onOpen).toHaveBeenCalledWith(cs);
  });

  it('flags a just-dropped chapter, and a historical study says so', () => {
    const { rerender } = render(
      <CaseStudyCard cs={caseStudy({ justDropped: true })} onOpen={vi.fn()} />,
    );
    expect(screen.getByText('Chapter just dropped')).toBeInTheDocument();

    rerender(
      <CaseStudyCard
        cs={caseStudy({ justDropped: false, status: 'historical' })}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByText('Chapter just dropped')).not.toBeInTheDocument();
    expect(screen.getByText(/Historical/)).toBeInTheDocument();
  });
});

/* Both modals portal into document.body and implement their own focus trap. The trap is
 * driven with fireEvent rather than userEvent.tab(): userEvent emulates tab order itself
 * and would move focus on its own, which muddies any assertion about what the component
 * handler actually did. */
// NOTE the two close buttons are labelled differently ('Close' vs 'Close modal').
// Parameterised rather than normalised: changing a component's accessible name is a
// behaviour change, and this move is not the place for one.
describe.each([
  ['CaseStudyModal', 'Close', (onClose: () => void) => <CaseStudyModal cs={caseStudy()} onClose={onClose} />],
  ['FailureModal', 'Close modal', (onClose: () => void) => <FailureModal entry={failureEntry()} onClose={onClose} />],
] as const)('%s', (_name, closeLabel, renderModal) => {
  it('focuses the close button on mount', () => {
    render(renderModal(vi.fn()));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: closeLabel }));
  });

  it('closes on Escape', () => {
    const onClose = vi.fn();
    render(renderModal(onClose));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('closes on a backdrop click but not on a click inside the panel', () => {
    const onClose = vi.fn();
    render(renderModal(onClose));

    fireEvent.click(screen.getByRole('dialog'));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('dialog').parentElement!);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('keeps focus inside on Tab and Shift+Tab', () => {
    render(renderModal(vi.fn()));
    const close = screen.getByRole('button', { name: closeLabel });

    // The panel holds exactly one focusable element, so first === last and both wrap
    // branches resolve to "stay here".
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(close);

    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(close);
  });

  it('ignores keys that are neither Escape nor Tab', () => {
    const onClose = vi.fn();
    render(renderModal(onClose));
    fireEvent.keyDown(document, { key: 'a' });
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe('library cards and tabs', () => {
  it('failure card surfaces the lesson and opens', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const entry = failureEntry();
    render(
      <FailureCard
        deal={entry.deal}
        category={entry.category}
        lesson={entry.lesson}
        quarter={entry.quarter}
        entry={entry}
        onOpen={onOpen}
      />,
    );

    expect(screen.getByText(entry.lesson)).toBeInTheDocument();
    await user.click(screen.getByRole('button'));
    expect(onOpen).toHaveBeenCalledWith(entry);
  });

  it('module card renders a course', () => {
    const course = COURSE_SECTIONS[0].courses[0];
    render(<ModuleCard course={course} />);
    expect(screen.getByText(course.title)).toBeInTheDocument();
  });

  it('spotlight card renders the featured course for a mode', () => {
    render(<SpotlightCard course={SPOTLIGHT.veteran} />);
    expect(screen.getByText(SPOTLIGHT.veteran.title)).toBeInTheDocument();
  });

  it('course section renders its heading and courses', () => {
    const section = COURSE_SECTIONS[0];
    render(<CourseSection title={section.title} courses={section.courses} revealDelay={80} />);
    expect(screen.getByRole('heading', { name: section.title })).toBeInTheDocument();
    expect(screen.getByText(section.courses[0].title)).toBeInTheDocument();
  });

  it('courses tab shows a different spotlight per mode', () => {
    const { unmount } = render(<CoursesTab mode="veteran" />);
    expect(screen.getByText(SPOTLIGHT.veteran.title)).toBeInTheDocument();
    unmount();

    render(<CoursesTab mode="newbie" />);
    expect(screen.getByText(SPOTLIGHT.newbie.title)).toBeInTheDocument();
  });

  it('failure library tab hands the clicked entry back to its caller', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<FailureLibraryTab onOpen={onOpen} />);

    await user.click(screen.getAllByRole('button')[0]);
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it('case studies tab opens and closes its own modal', async () => {
    const user = userEvent.setup();
    render(<CaseStudiesTab />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await user.click(screen.getAllByRole('button')[0]);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(CASE_STUDIES[0].headline);

    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
