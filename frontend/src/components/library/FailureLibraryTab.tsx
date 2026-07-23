import type { FailureEntry } from '@/types';
import { FAILURE_LIBRARY } from '@/data/library';
import { FailureCard } from '@/components/library/FailureCard';

export function FailureLibraryTab({ onOpen }: { onOpen: (e: FailureEntry) => void }) {
  return (
    <div>
      <p className="text-sm text-ink-2 leading-base mb-6 max-w-[60ch]">
        Post-mortems of churned and lost deals, annotated for what could have changed the outcome.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {FAILURE_LIBRARY.map(entry => (
          <FailureCard
            key={entry.id}
            {...entry}
            entry={entry}
            onOpen={onOpen}
          />
        ))}
      </div>
    </div>
  );
}
