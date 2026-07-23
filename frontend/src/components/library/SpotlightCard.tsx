import type { SpotlightCourse } from '@/types';
import { StarIcon } from '@/components/icons';

export function SpotlightCard({ course }: { course: SpotlightCourse }) {
  return (
    <div className="anim-spotlight border-[1.5px] border-line rounded-lg p-8 mb-10 bg-bg shadow-low">
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-accent-on bg-accent px-2 py-[3px] rounded-full mb-4">
        <StarIcon />
        Recommended for you
      </span>
      <h2 className="text-xl font-bold text-ink mb-3 tracking-[-0.02em] text-balance">{course.title}</h2>
      <p className="text-base text-ink-2 leading-base text-pretty mb-4">{course.desc}</p>
      <div className="flex items-center gap-2 mb-4">
        <span className="text-sm font-medium text-ink-2">{course.modules} modules</span>
        <span className="text-ink-placeholder">·</span>
        <span className="text-sm font-medium text-ink-2">{course.readTime}</span>
      </div>
      <div className="flex flex-wrap gap-2 mb-6">
        {course.tags.map(tag => (
          <span key={tag} className="inline-flex items-center gap-1 px-2 py-[3px] rounded-full text-[11px] font-semibold leading-none whitespace-nowrap bg-surface-raised text-ink-2 border border-line">{tag}</span>
        ))}
      </div>
      <button className="inline-flex items-center gap-2 h-7 px-3 rounded-sm text-xs font-semibold bg-primary text-white cursor-pointer mt-2 transition duration-fast ease-out-quart hover:bg-primary-hover hover:-translate-y-px hover:shadow-[0_4px_12px_oklch(0.440_0.180_256_/_0.3)]">Start module</button>
    </div>
  );
}
