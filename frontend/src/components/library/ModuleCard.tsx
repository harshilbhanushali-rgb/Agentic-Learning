import type { Course } from '@/types';
export function ModuleCard({ course }: { course: Course }) {
  return (
    <div
      className="border-[1.5px] border-line rounded-md p-5 flex flex-col gap-3 cursor-pointer bg-bg min-h-[140px] text-left transition duration-fast ease-out-quart hover:shadow-low hover:-translate-y-0.5"
      role="button"
      tabIndex={0}
    >
      <h3 className="text-base font-semibold text-ink leading-snug text-balance">{course.title}</h3>
      <p className="text-sm text-ink-2 leading-base line-clamp-2 flex-1">{course.desc}</p>
      <div className="flex flex-wrap gap-1 mt-auto">
        {course.tags.map(tag => (
          <span key={tag} className="inline-flex items-center gap-1 px-2 py-[3px] rounded-full text-[11px] font-semibold leading-none whitespace-nowrap bg-surface-raised text-ink-2 border border-line">{tag}</span>
        ))}
      </div>
    </div>
  );
}
