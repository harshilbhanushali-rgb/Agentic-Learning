import type { Mode } from '@/types';
import { SPOTLIGHT, COURSE_SECTIONS } from '@/data/library';
import { SpotlightCard } from '@/components/library/SpotlightCard';
import { CourseSection } from '@/components/library/CourseSection';

export function CoursesTab({ mode }: { mode: Mode }) {
  return (
    <div>
      <SpotlightCard course={SPOTLIGHT[mode]} />
      {COURSE_SECTIONS.map((section, i) => (
        <CourseSection
          key={section.title}
          title={section.title}
          courses={section.courses}
          revealDelay={80 + i * 100}
        />
      ))}
    </div>
  );
}
