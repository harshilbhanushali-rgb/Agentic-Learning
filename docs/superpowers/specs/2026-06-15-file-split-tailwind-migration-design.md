# CS-Platform: File Split + Tailwind Migration

**Date:** 2026-06-15  
**Status:** Approved  
**Scope:** Break up large page files + globals.css; migrate all styling to Tailwind CSS (Option A — full migration)

---

## Problem

Three files have grown too large to maintain:

| File | Lines | Problem |
| --- | --- | --- |
| `src/app/globals.css` | 3,844 | Entire design system in one file — tokens, shell, workspace, library, animations |
| `src/app/workspace/page.js` | 1,059 | Data, hooks, 18 components, 14 icons all in one file |
| `src/app/library/page.js` | 599 | Data, hooks, 10 components, 3 icons all in one file |
| `useMode()` hook | — | Duplicated in both page files |

---

## Approach: Pure Tailwind + Extracted Components

Install Tailwind CSS. Move all design tokens into `tailwind.config.js`. Split every component into its own file. Extract mock data to `src/data/`. globals.css shrinks to ~60 lines.

No CSS Modules. No hybrid. One styling system.

---

## New Directory Structure

```text
src/
  app/
    globals.css              # ~60 lines: @tailwind directives + custom utilities only
    layout.js                # unchanged
    page.js                  # unchanged (redirect)
    workspace/
      page.js                # ~30 lines: page shell + imports only
    library/
      page.js                # ~40 lines: page shell + imports only
    simulator/
      page.js                # unchanged stub

  components/
    AppShell.js              # CSS converted to Tailwind inline; structure unchanged

    icons/
      index.js               # all 14 icon components as named exports

    shared/
      TQItem.js              # test queue row (used by workspace veteran + newbie)
      RadarBriefingPanel.js  # briefing panel: clip card + AI tip + waterfall steps
      RadarRow.js            # compact radar row (used by NewbieRadarCard)
      RadarDeckStack.js      # deck stack + RadarDeckCard + RadarDeckNav (veteran)

    workspace/
      WorkspaceGreeting.js
      EgoTrapCard.js
      WeeklyRadarCard.js
      TestQueuePanel.js
      KnowledgeDropsPanel.js
      NewbieGreeting.js
      NewbieTrackHero.js
      NewbieRadarCard.js
      NewbieTestQueuePanel.js
      BloomCard.js

    library/
      SpotlightCard.js
      ModuleCard.js
      CourseSection.js
      CoursesTab.js
      CaseStudyCard.js
      CaseStudyModal.js
      CaseStudiesTab.js
      FailureCard.js
      FailureModal.js
      FailureLibraryTab.js

  data/
    workspace.js             # all workspace mock data constants
    library.js               # all library mock data constants + csBars utility

  hooks/
    useMode.js               # single source of truth for the mode hook
```

---

## Tailwind Config Strategy

All CSS custom properties from globals.css move to `tailwind.config.js` as theme extensions:

```js
theme: {
  extend: {
    colors: {
      bg:              'oklch(1.000 0.000 0)',
      surface:         'oklch(0.967 0.006 256)',
      'surface-raised':'oklch(0.942 0.008 256)',
      border:          'oklch(0.882 0.009 256)',
      'border-subtle': 'oklch(0.928 0.006 256)',
      ink:             'oklch(0.135 0.014 256)',
      'ink-2':         'oklch(0.420 0.010 256)',
      'ink-placeholder':'oklch(0.465 0.010 256)',
      primary:         'oklch(0.428 0.198 256)',
      'primary-hover': 'oklch(0.372 0.208 256)',
      'primary-active':'oklch(0.322 0.215 256)',
      'primary-surface':'oklch(0.948 0.034 256)',
      'primary-subtle':'oklch(0.968 0.020 256)',
      accent:          'oklch(0.858 0.092 80)',
      'accent-on':     'oklch(0.210 0.055 75)',
      'accent-ink':    'oklch(0.320 0.085 75)',
      'accent-surface':'oklch(0.965 0.028 80)',
      success:         'oklch(0.415 0.140 150)',
      'success-surface':'oklch(0.960 0.038 150)',
      warning:         'oklch(0.415 0.128 68)',
      'warning-surface':'oklch(0.964 0.028 68)',
      error:           'oklch(0.475 0.190 25)',
      'error-surface': 'oklch(0.960 0.038 25)',
    },
    borderRadius: {
      sm: '4px', md: '8px', lg: '12px', xl: '20px',
    },
    boxShadow: {
      low:     '0 1px 3px oklch(0% 0 0 / 0.05), 0 2px 12px oklch(0% 0 0 / 0.03)',
      ambient: '0 4px 20px oklch(0% 0 0 / 0.08), 0 1px 4px oklch(0% 0 0 / 0.04)',
      lifted:  '0 8px 32px oklch(0% 0 0 / 0.12), 0 2px 8px oklch(0% 0 0 / 0.06)',
    },
    transitionTimingFunction: {
      'out-quart': 'cubic-bezier(0.25, 1, 0.5, 1)',
      'out-quint': 'cubic-bezier(0.22, 1, 0.36, 1)',
      'out-expo':  'cubic-bezier(0.16, 1, 0.3, 1)',
    },
    transitionDuration: {
      fast: '120ms', base: '200ms', slow: '320ms', enter: '280ms',
    },
    zIndex: {
      dropdown: '100', sticky: '200',
      'modal-backdrop': '300', modal: '400', toast: '500',
    },
  }
}
```

Result: `text-ink`, `bg-surface`, `shadow-ambient`, `rounded-md`, `duration-base` etc. work as first-class Tailwind utilities.

---

## globals.css After Migration

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

/* Expand/collapse animation: grid-template-rows 0fr → 1fr */
@layer utilities {
  .grid-rows-0fr { grid-template-rows: 0fr; }
  .grid-rows-1fr { grid-template-rows: 1fr; }
}

/* Radar deck pseudo-element stacking (back/mid cards) — cannot live in JSX */
@layer components {
  /* ~20 lines of radar deck ::before / ::after card depth styles */
}

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
}
```

3,844 lines → ~60 lines.

---

## CSS Migration: Special Cases

### 1. Expand/collapse (ego trap mirror, radar briefing, newbie track)

Current pattern: `grid-template-rows: 0fr` → `1fr` via `.is-open` class.  
After: toggle between `grid-rows-0fr` and `grid-rows-1fr` custom utilities. The inner `overflow-hidden min-h-0` stays as Tailwind utilities.

### 2. Radar deck 3D card stacking

Back/mid card depth uses `::before`/`::after` pseudo-elements with `translateY` + `scaleX`. These cannot be expressed in JSX classNames. They stay as ~20 lines in `@layer components` inside globals.css.

### 3. All other component styles

Direct 1:1 Tailwind equivalents — flex/grid layout, spacing, color, typography, border, shadow, transitions. Custom class names (`et-card`, `radar-row`, etc.) disappear entirely.

---

## Data Extraction

### `src/data/workspace.js`

Exports: `EGO_TRAPS`, `RADAR_MEETINGS`, `TEST_QUEUE`, `KNOWLEDGE_DROPS`, `NEWBIE_TRACK`, `NEWBIE_RADAR_MEETINGS`, `NEWBIE_TEST_QUEUE`, `BLOOM_STAGES`

### `src/data/library.js`

Exports: `SPOTLIGHT`, `COURSE_SECTIONS`, `CASE_STUDIES`, `FAILURE_LIBRARY`, `csBars`

### `src/hooks/useMode.js`

Single `useMode()` hook. Currently duplicated in both page files — extracted once, imported by workspace/page.js, library/page.js, and AppShell.js.

---

## Implementation Notes

- Every extracted component file that uses `useState`/`useEffect` needs `'use client'` at the top — this includes all workspace + library components and the `useMode` hook file.
- Pure presentational components (no hooks, no event handlers) do **not** need `'use client'`.
- Tailwind installation: `npm install -D tailwindcss postcss autoprefixer` + `npx tailwindcss init -p`, then configure `content` paths to include `./src/**/*.{js,jsx}`.
- `next.config.js` does not need changes — Next.js 14 picks up PostCSS config automatically.

---

## What Does NOT Change

- `AppShell.js` structure — same component, CSS converted to Tailwind inline
- `layout.js` — unchanged
- `page.js` (root redirect) — unchanged  
- `simulator/page.js` — unchanged stub
- All routing — unchanged
- All component logic and state — unchanged
- The mode system (localStorage + CustomEvent) — unchanged
- Dark mode token-readiness — preserved via Tailwind's `dark:` variant

---

## Success Criteria

- `globals.css` under 80 lines
- `workspace/page.js` under 40 lines
- `library/page.js` under 50 lines
- No file in `src/components/` exceeds 200 lines
- App renders identically before and after (visual regression: none)
- `npm run build` passes
- `npm run lint` passes
- No custom CSS class names remain in JSX (all Tailwind utilities)
