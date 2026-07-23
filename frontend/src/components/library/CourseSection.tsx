import type { Course } from '@/types';
import type { CSSProperties } from 'react';
import { ModuleCard } from '@/components/library/ModuleCard';

export function CourseSection({ title, courses, revealDelay }: { title: string; courses: Course[]; revealDelay: number }) {
  return (
    <div className="mb-10">
      <div className="lib-section-header flex items-center justify-between mb-5" style={{ '--reveal-delay': `${revealDelay}ms` } as CSSProperties}>
        <h2 className="text-lg font-semibold text-ink tracking-[-0.01em]">{title}</h2>
        <button className="inline-flex items-center text-primary text-sm px-2 h-[30px] font-medium rounded-sm transition duration-fast ease-out-quart hover:bg-primary-subtle">View all</button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        {courses.map(course => (
          <ModuleCard key={course.id} course={course} />
        ))}
      </div>
    </div>
  );
}
