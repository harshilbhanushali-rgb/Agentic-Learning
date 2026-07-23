# File Split + Tailwind Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break the three oversized files (`globals.css` 3,844 lines, `workspace/page.js` 1,059 lines, `library/page.js` 599 lines) into focused per-component files and migrate all styling to Tailwind CSS utilities.

**Architecture:** Install Tailwind. Move design tokens to `tailwind.config.js` as references to the CSS custom properties that stay in `globals.css` (so dark mode keeps working through `[data-theme="dark"]`). Split each page into one file per component under `src/components/{workspace,library,shared}/`, extract icons to `src/components/icons/`, mock data to `src/data/`, and the duplicated `useMode` hook to `src/hooks/`. globals.css shrinks to ~120 lines: token `:root`/dark blocks + base reset + custom utilities + radar-deck pseudo-stacking + keyframes that can't be expressed inline.

**Tech Stack:** Next.js 14 App Router (JavaScript), Tailwind CSS 3, PostCSS, Autoprefixer, React 18.

---

## Verification Note

There is no test framework. Every task is verified by `npm run build` (must compile) and visual parity. The final task runs `npm run build` + `npm run lint`. Intermediate tasks that add files without wiring them in are verified by build success; tasks that swap a page over are verified by build + manual visual check.

Because tokens remain as CSS variables referenced from the Tailwind config, **all existing `var(--color-*)` inline styles continue to work unchanged** — we do not need to convert inline `style={{...}}` props that use CSS vars. We only convert `className` custom classes to Tailwind utilities.

---

## File Structure

```text
src/
  app/
    globals.css              # ~120 lines: tokens + base + custom utilities + radar-deck + keyframes
    workspace/page.js        # shell: 'use client' + useMode + layout switch
    library/page.js          # shell: 'use client' + useMode + tabs + modal state
  components/
    AppShell.js              # CSS classes → Tailwind inline
    icons/index.js           # all icons, named exports
    shared/
      TQItem.js
      RadarBriefingPanel.js
      RadarRow.js
      RadarDeckStack.js      # + RadarDeckCard + RadarDeckNav
    workspace/
      WorkspaceGreeting.js  NewbieGreeting.js
      EgoTrapCard.js        NewbieTrackHero.js
      WeeklyRadarCard.js    NewbieRadarCard.js
      TestQueuePanel.js     NewbieTestQueuePanel.js
      KnowledgeDropsPanel.js  BloomCard.js
    library/
      SpotlightCard.js  ModuleCard.js  CourseSection.js  CoursesTab.js
      CaseStudyCard.js  CaseStudyModal.js  CaseStudiesTab.js
      FailureCard.js    FailureModal.js   FailureLibraryTab.js
  data/
    workspace.js  library.js
  hooks/
    useMode.js
```

---

### Task 1: Install Tailwind CSS

**Files:**
- Modify: `package.json` (via npm)
- Create: `postcss.config.js`, `tailwind.config.js` (regenerated in Task 2)

- [ ] **Step 1: Install dev dependencies**

Run:
```bash
npm install -D tailwindcss@3 postcss autoprefixer
```
Expected: `added N packages` with no error; `tailwindcss`, `postcss`, `autoprefixer` appear in `package.json` devDependencies.

- [ ] **Step 2: Generate config files**

Run:
```bash
npx tailwindcss init -p
```
Expected: creates `tailwind.config.js` and `postcss.config.js` in project root. Console prints `Created Tailwind CSS config file: tailwind.config.js` and `Created PostCSS config file: postcss.config.js`.

- [ ] **Step 3: Verify postcss.config.js**

Confirm `postcss.config.js` contains:
```js
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```
If `npx` produced a different shape, overwrite it with the above.

- [ ] **Step 4: Commit**

```bash
git add package.json package-lock.json postcss.config.js tailwind.config.js
git commit -m "build: install and scaffold Tailwind CSS"
```

---

### Task 2: Configure tailwind.config.js with token references

**Files:**
- Modify: `tailwind.config.js`

- [ ] **Step 1: Write the full config**

Replace the entire contents of `tailwind.config.js` with:

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,jsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg:                'var(--color-bg)',
        surface:           'var(--color-surface)',
        'surface-raised':  'var(--color-surface-raised)',
        line:              'var(--color-border)',
        'line-subtle':     'var(--color-border-subtle)',
        ink:               'var(--color-ink)',
        'ink-2':           'var(--color-ink-2)',
        'ink-placeholder': 'var(--color-ink-placeholder)',
        primary:           'var(--color-primary)',
        'primary-hover':   'var(--color-primary-hover)',
        'primary-active':  'var(--color-primary-active)',
        'primary-surface': 'var(--color-primary-surface)',
        'primary-subtle':  'var(--color-primary-subtle)',
        accent:            'var(--color-accent)',
        'accent-on':       'var(--color-accent-on)',
        'accent-ink':      'var(--color-accent-ink)',
        'accent-surface':  'var(--color-accent-surface)',
        success:           'var(--color-success)',
        'success-surface': 'var(--color-success-surface)',
        warning:           'var(--color-warning)',
        'warning-surface': 'var(--color-warning-surface)',
        error:             'var(--color-error)',
        'error-surface':   'var(--color-error-surface)',
        // sidebar palette
        'sb-bg':       'var(--sb-bg)',
        'sb-surface':  'var(--sb-surface)',
        'sb-border':   'var(--sb-border)',
        'sb-ink':      'var(--sb-ink)',
        'sb-ink-2':    'var(--sb-ink-2)',
        'sb-ink-3':    'var(--sb-ink-3)',
        'sb-active-bg':'var(--sb-active-bg)',
        'sb-hover-bg': 'var(--sb-hover-bg)',
        'sb-badge-bg': 'var(--sb-badge-bg)',
      },
      fontFamily: {
        sans: ['var(--font-sans)'],
        mono: ['var(--font-mono)'],
      },
      fontSize: {
        xs:   'var(--text-xs)',
        sm:   'var(--text-sm)',
        base: 'var(--text-base)',
        lg:   'var(--text-lg)',
        xl:   'var(--text-xl)',
        '2xl':'var(--text-2xl)',
        '3xl':'var(--text-3xl)',
      },
      fontWeight: {
        regular:  '400',
        medium:   '500',
        semibold: '600',
        bold:     '700',
      },
      lineHeight: {
        tight:   '1.2',
        snug:    '1.35',
        base:    '1.55',
        relaxed: '1.7',
      },
      spacing: {
        1:  'var(--space-1)',
        2:  'var(--space-2)',
        3:  'var(--space-3)',
        4:  'var(--space-4)',
        5:  'var(--space-5)',
        6:  'var(--space-6)',
        8:  'var(--space-8)',
        10: 'var(--space-10)',
        12: 'var(--space-12)',
        16: 'var(--space-16)',
        20: 'var(--space-20)',
      },
      borderRadius: {
        sm:   'var(--radius-sm)',
        md:   'var(--radius-md)',
        lg:   'var(--radius-lg)',
        xl:   'var(--radius-xl)',
        full: 'var(--radius-full)',
      },
      boxShadow: {
        low:     'var(--shadow-low)',
        ambient: 'var(--shadow-ambient)',
        lifted:  'var(--shadow-lifted)',
      },
      transitionTimingFunction: {
        'out-quart': 'cubic-bezier(0.25, 1, 0.5, 1)',
        'out-quint': 'cubic-bezier(0.22, 1, 0.36, 1)',
        'out-expo':  'cubic-bezier(0.16, 1, 0.3, 1)',
      },
      transitionDuration: {
        fast:  '120ms',
        base:  '200ms',
        slow:  '320ms',
        enter: '280ms',
      },
      zIndex: {
        dropdown:        '100',
        sticky:          '200',
        'modal-backdrop':'300',
        modal:           '400',
        toast:           '500',
        tooltip:         '600',
      },
      maxWidth: {
        content: 'var(--content-width)',
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 2: Verify build still compiles (no styling applied yet)**

Run:
```bash
npm run build
```
Expected: build succeeds. (globals.css still has all old classes; Tailwind is configured but its directives aren't injected until Task 3.)

- [ ] **Step 3: Commit**

```bash
git add tailwind.config.js
git commit -m "build: configure Tailwind theme to reference CSS variable tokens"
```

---

### Task 3: Rewrite globals.css to lean form

**Files:**
- Modify: `src/app/globals.css`

> **IMPORTANT:** Before editing, read the current `src/app/globals.css` in full to copy the EXACT `:root` token block (lines ~9-107), the dark-mode block (lines ~109-142), the layout-token block (lines ~1385-1400), the base reset, and the keyframes (`oracle-drop`, `lib-content-enter`, `lib-spotlight-enter`, `lib-reveal`, `pulse-dot`, `lib-backdrop-enter`, `lib-modal-enter`, plus the `pulse-dot`/live-dot keyframes used by `.et-live-dot` and `.oracle-live-dot`). Paste those verbatim into the new file in the marked sections. Do not retype token values from memory.

- [ ] **Step 1: Replace globals.css contents**

The new file structure (paste verbatim token/keyframe blocks where indicated):

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

/* ============================================================
   JOVEO CS PLATFORM — TOKENS + RESIDUAL STYLES
   Tailwind utilities cover component styling. This file keeps:
   1. CSS variable tokens (referenced by tailwind.config.js)
   2. Dark-mode token overrides
   3. Base reset / font wiring
   4. Custom utilities Tailwind can't express
   5. Radar-deck 3D pseudo-stacking
   6. Keyframe animations
   ============================================================ */

:root {
  /* PASTE the entire :root token block from the old globals.css
     (all --color-*, --font-*, --text-*, --weight-*, --leading-*,
      --space-*, --radius-*, --shadow-*, --ease-*, --dur-*, --z-*,
      --nav-height, --content-width, --content-pad) VERBATIM here. */
}

[data-theme="dark"] {
  /* PASTE the entire [data-theme="dark"] override block VERBATIM here. */
}

:root {
  /* PASTE the LAYOUT TOKENS :root block (--sidebar-width, --topbar-height,
     --right-panel-width, and all --sb-* sidebar palette vars) VERBATIM here. */
}

/* ── BASE RESET ──────────────────────────────────────────── */

* { margin: 0; padding: 0; box-sizing: border-box; }

html { -webkit-text-size-adjust: 100%; }

body {
  font-family: var(--font-sans);
  background: var(--color-bg);
  color: var(--color-ink);
  line-height: var(--leading-base);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

button { font-family: inherit; }

/* ── CUSTOM UTILITIES ────────────────────────────────────── */

@layer utilities {
  /* Expand/collapse: grid-template-rows 0fr → 1fr */
  .grid-rows-0fr { grid-template-rows: 0fr; }
  .grid-rows-1fr { grid-template-rows: 1fr; }
}

/* ── RADAR DECK 3D STACKING ──────────────────────────────── */
/* These rely on data-slot attribute + calc() positioning that
   cannot be expressed as inline Tailwind utilities. Kept as-is. */

.radar-deck-wrap {
  position: relative;
  padding: 20px var(--space-5) var(--space-4);
}

.radar-deck-card {
  width: 100%;
  background: var(--color-bg);
  border: 1.5px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-4) var(--space-5);
  box-sizing: border-box;
  position: relative;
  overflow: hidden;
  transition:
    transform 200ms var(--ease-out-quart),
    opacity   200ms var(--ease-out-quart),
    filter    200ms var(--ease-out-quart);
}

.radar-deck-card[data-slot="back"] {
  position: absolute;
  top: 0;
  left: calc(var(--space-5) + 12px);
  right: calc(var(--space-5) + 12px);
  width: auto;
  height: 12px;
  overflow: hidden;
  transform: none;
  opacity: 0.4;
  filter: none;
  z-index: 1;
  pointer-events: none;
}

.radar-deck-card[data-slot="mid"] {
  position: absolute;
  top: 4px;
  left: calc(var(--space-5) + 6px);
  right: calc(var(--space-5) + 6px);
  width: auto;
  height: 16px;
  overflow: hidden;
  transform: none;
  opacity: 0.6;
  filter: none;
  z-index: 2;
  pointer-events: none;
}

.radar-deck-card[data-slot="front"] {
  transform: none;
  opacity: 1;
  filter: none;
  z-index: 3;
  box-shadow: 0 2px 10px oklch(0 0 0 / 0.05);
  transition:
    box-shadow 200ms var(--ease-out-quart),
    transform 200ms var(--ease-out-quart);
}

.radar-deck-card[data-slot="front"]:not(.is-open):hover {
  box-shadow: 0 6px 20px oklch(0 0 0 / 0.09);
  transform: translateY(-2px);
}

.radar-deck-card[data-slot="front"].is-open {
  transform: none;
  box-shadow: 0 4px 20px oklch(0 0 0 / 0.07);
}

.deck-is-open .radar-deck-card[data-slot="back"] { opacity: 0.2; }
.deck-is-open .radar-deck-card[data-slot="mid"]  { opacity: 0.3; }

/* ── KEYFRAMES ───────────────────────────────────────────── */
/* PASTE all @keyframes blocks from the old globals.css VERBATIM here:
   oracle-drop, lib-content-enter, lib-spotlight-enter, lib-reveal,
   pulse-dot (live-dot pulse), lib-backdrop-enter, lib-modal-enter,
   and any others referenced. Search the old file for "@keyframes". */

/* ── REDUCED MOTION ──────────────────────────────────────── */

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 2: Before deleting, grep the old file for every `@keyframes` and confirm each is pasted into the new file**

Run:
```bash
grep -n "@keyframes" src/app/globals.css
```
Expected: every keyframe name printed must exist in your new file's KEYFRAMES section. If `animation:` declarations elsewhere reference a keyframe (e.g. `.et-live-dot`, `.oracle-live-dot`, `.lib-cs-drop-dot`), the keyframe must be preserved AND those elements will need an inline `animate-*` or a small residual rule — see Step 3.

- [ ] **Step 3: Preserve animated dot indicators**

The pulsing dots (`.et-live-dot`, `.oracle-live-dot`, `.lib-cs-drop-dot`, `.pulse-dot`, `.radar-chip` live dots) use a keyframe animation that's awkward inline. Add a residual utility block to globals.css after KEYFRAMES:

```css
@layer components {
  .anim-pulse-dot {
    animation: pulse-dot 2s var(--ease-out-quart) infinite;
  }
}
```
Components that had `.et-live-dot` etc. will render the dot with Tailwind classes for size/color/shape PLUS `anim-pulse-dot` for the animation. (Referenced in Tasks 12, 24, 34.)

- [ ] **Step 4: Verify build compiles**

Run:
```bash
npm run build
```
Expected: build FAILS or renders unstyled, because pages still reference deleted classes like `.workspace-body`. **This is expected at this checkpoint** — the build command itself should still *compile* (CSS class absence is not a compile error in Next.js). Confirm it compiles without a JS/PostCSS error. Visual breakage is fixed as components migrate in later tasks.

- [ ] **Step 5: Commit**

```bash
git add src/app/globals.css
git commit -m "refactor(css): reduce globals.css to tokens + utilities + keyframes"
```

---

### Task 4: Create useMode hook

**Files:**
- Create: `src/hooks/useMode.js`

- [ ] **Step 1: Write the hook**

```js
'use client';

import { useState, useEffect } from 'react';

export function useMode() {
  const [mode, setMode] = useState('veteran');
  useEffect(() => {
    setMode(localStorage.getItem('cs-mode') || 'veteran');
    const handler = (e) => setMode(e.detail);
    window.addEventListener('cs-mode-change', handler);
    return () => window.removeEventListener('cs-mode-change', handler);
  }, []);
  return mode;
}
```

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles (file is unused so far).

- [ ] **Step 3: Commit**

```bash
git add src/hooks/useMode.js
git commit -m "refactor: extract useMode hook to src/hooks"
```

---

### Task 5: Create src/data/workspace.js

**Files:**
- Create: `src/data/workspace.js`

- [ ] **Step 1: Move all workspace constants**

Copy the following constants VERBATIM from `src/app/workspace/page.js` and prefix each with `export`: `EGO_TRAPS`, `RADAR_MEETINGS`, `TEST_QUEUE`, `KNOWLEDGE_DROPS`, `NEWBIE_TRACK`, `NEWBIE_RADAR_MEETINGS`, `NEWBIE_TEST_QUEUE`, `BLOOM_STAGES`.

The file is pure data (no JSX, no hooks) — **no `'use client'` needed**. Structure:

```js
/* Workspace mock data — extracted from workspace/page.js */

export const EGO_TRAPS = [ /* ...verbatim array... */ ];

export const RADAR_MEETINGS = [ /* ...verbatim array... */ ];

export const TEST_QUEUE = [ /* ...verbatim array... */ ];

export const KNOWLEDGE_DROPS = [ /* ...verbatim array... */ ];

export const NEWBIE_TRACK = { /* ...verbatim object... */ };

export const NEWBIE_RADAR_MEETINGS = [ /* ...verbatim array... */ ];

export const NEWBIE_TEST_QUEUE = [ /* ...verbatim array... */ ];

export const BLOOM_STAGES = [ /* ...verbatim array... */ ];
```

Source line ranges in current `workspace/page.js`: EGO_TRAPS 20-161, RADAR_MEETINGS 163-206, TEST_QUEUE 208-213, KNOWLEDGE_DROPS 215-219, NEWBIE_TRACK 223-237, NEWBIE_RADAR_MEETINGS 239-253, NEWBIE_TEST_QUEUE 255-260, BLOOM_STAGES 262-267.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles (file unused so far).

- [ ] **Step 3: Commit**

```bash
git add src/data/workspace.js
git commit -m "refactor: extract workspace mock data to src/data"
```

---

### Task 6: Create src/data/library.js

**Files:**
- Create: `src/data/library.js`

- [ ] **Step 1: Move all library constants + csBars**

Copy VERBATIM from `src/app/library/page.js` and export: `SPOTLIGHT` (21-38), `COURSE_SECTIONS` (40-74), `CASE_STUDIES` (76-165), `csBars` function (168-177), `FAILURE_LIBRARY` (179-236). Pure data/util — **no `'use client'`**.

```js
/* Library mock data + helpers — extracted from library/page.js */

export const SPOTLIGHT = { /* ...verbatim... */ };

export const COURSE_SECTIONS = [ /* ...verbatim... */ ];

export const CASE_STUDIES = [ /* ...verbatim... */ ];

/* Deterministic bar heights (SSR-safe — no Math.random / Date) */
export function csBars(seed, n = 30) {
  let x = 0;
  for (let i = 0; i < seed.length; i++) x = (x * 31 + seed.charCodeAt(i)) % 9973;
  const out = [];
  for (let i = 0; i < n; i++) {
    x = (x * 1103515245 + 12345) & 0x7fffffff;
    out.push(26 + (x % 70)); // 26–96%
  }
  return out;
}

export const FAILURE_LIBRARY = [ /* ...verbatim... */ ];
```

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/data/library.js
git commit -m "refactor: extract library mock data to src/data"
```

---

### Task 7: Create src/components/icons/index.js

**Files:**
- Create: `src/components/icons/index.js`

- [ ] **Step 1: Move all icon components as named exports**

Collect every icon function from BOTH page files and AppShell.js into one module. Convert inline `style={{ color: 'var(--color-ink-placeholder)' }}` etc. — keep them as-is (they use CSS vars, still valid). Prefix each `function` with `export`. These are pure presentational SVGs — **no `'use client'`**.

From `workspace/page.js`: `ChevronRightIcon`, `ChevronDownIcon`, `ChevronLeftIcon`, `ChevronUpIcon`, `ClockIcon`, `WaveIcon`, `PersonIcon`, `PlayIcon`, `SparkleIcon`, `WFCheckIcon`, `WFLockIcon`, `BloomDotIcon`, `TQCheckIcon`, `TQRadioIcon`, `TQLockIcon`, `WaveformViz` (lines 1001-1160).

From `library/page.js`: `StarIcon`, `PeopleIcon`, `ArrowIcon` (lines 240-264).

From `AppShell.js`: `MenuIcon`, `SearchIcon`, `BellIcon`, `BellSmIcon`, `ChatIcon`, `SunIcon`, `MoonIcon`, `BookmarkIcon` (lines 259-343).

```js
/* All icon components — named exports. Pure SVG, no client directive. */

export function ChevronRightIcon() { /* ...verbatim... */ }
export function ChevronDownIcon() { /* ...verbatim... */ }
export function ChevronLeftIcon() { /* ...verbatim... */ }
export function ChevronUpIcon() { /* ...verbatim... */ }
export function ClockIcon() { /* ...verbatim... */ }
export function WaveIcon() { /* ...verbatim... */ }
export function PersonIcon() { /* ...verbatim... */ }
export function PlayIcon() { /* ...verbatim... */ }
export function SparkleIcon() { /* ...verbatim... */ }
export function WFCheckIcon() { /* ...verbatim... */ }
export function WFLockIcon() { /* ...verbatim... */ }
export function BloomDotIcon() { /* ...verbatim... */ }
export function TQCheckIcon() { /* ...verbatim... */ }
export function TQRadioIcon() { /* ...verbatim... */ }
export function TQLockIcon() { /* ...verbatim... */ }
export function WaveformViz() { /* ...verbatim... */ }
export function StarIcon() { /* ...verbatim... */ }
export function PeopleIcon() { /* ...verbatim... */ }
export function ArrowIcon() { /* ...verbatim... */ }
export function MenuIcon() { /* ...verbatim... */ }
export function SearchIcon() { /* ...verbatim... */ }
export function BellIcon() { /* ...verbatim... */ }
export function BellSmIcon() { /* ...verbatim... */ }
export function ChatIcon() { /* ...verbatim... */ }
export function SunIcon() { /* ...verbatim... */ }
export function MoonIcon() { /* ...verbatim... */ }
export function BookmarkIcon() { /* ...verbatim... */ }
```

> Note: `ArrowIcon` keeps its `className="lib-fl-readmore-arrow"` — that class is used for a hover-driven transform. Add a residual rule for it (see Task 30). Leave the className on the SVG.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/icons/index.js
git commit -m "refactor: consolidate all icons into src/components/icons"
```

---

## Tailwind Class Reference (apply consistently across Tasks 8-34)

When converting custom classes, use these mappings. Border color token is `line` (not `border`) to avoid clashing with Tailwind's `border` width utility.

| Old CSS | Tailwind |
| --- | --- |
| `border: 1px solid var(--color-border)` | `border border-line` |
| `border: 1px solid var(--color-border-subtle)` | `border border-line-subtle` |
| `background: var(--color-surface)` | `bg-surface` |
| `color: var(--color-ink-2)` | `text-ink-2` |
| `border-radius: var(--radius-md)` | `rounded-md` |
| `box-shadow: var(--shadow-ambient)` | `shadow-ambient` |
| `padding: var(--space-4) var(--space-5)` | `py-4 px-5` |
| `gap: var(--space-2)` | `gap-2` |
| `font-size: var(--text-sm)` | `text-sm` |
| `font-weight: 600` | `font-semibold` |
| `transition ... var(--dur-fast)` | `transition duration-fast ease-out-quart` |
| `grid-template-rows: 0fr` (collapsed) | `grid grid-rows-0fr` |
| `grid-template-rows: 1fr` (expanded) | `grid-rows-1fr` |

For pixel values with no token (e.g. `font-size: 11px`, `width: 28px`), use arbitrary values: `text-[11px]`, `w-7` (28px = `w-7`), or `w-[28px]`. Prefer the scale where it maps cleanly (4px grid), arbitrary otherwise.

> **Migration method for each component task:** Read the component's JSX from the source page file and its corresponding CSS rules from the OLD globals.css (use git: `git show HEAD~N:src/app/globals.css` or the pre-Task-3 commit). Translate each custom class to Tailwind utilities inline. Keep all logic, props, state, refs, event handlers, and `aria-*` attributes identical. Keep inline `style={{...}}` that uses CSS vars unchanged.

---

### Task 8: shared/TQItem.js

**Files:**
- Create: `src/components/shared/TQItem.js`

- [ ] **Step 1: Write the component**

Source JSX: `workspace/page.js` lines 973-997. Source CSS: old globals.css `.tq-item`, `.tq-item--complete/active/locked`, `.tq-indicator`, `.tq-item-body`, `.tq-item-title`, `.tq-item-meta`, `.tq-item-note`, `.tq-take-btn` (≈ lines 2455-2600).

```js
'use client';

import { TQCheckIcon, TQRadioIcon, TQLockIcon } from '@/components/icons';

export function TQItem({ item, tierLabel }) {
  const stateClasses = {
    complete: 'opacity-100',
    active:   'opacity-100',
    locked:   'opacity-50',
  }[item.status] || '';

  return (
    <div
      className={`flex gap-3 py-3 px-4 rounded-md border border-line-subtle ${stateClasses}`}
      title={item.status === 'locked' ? 'Complete the previous test to unlock' : undefined}
      aria-disabled={item.status === 'locked' ? 'true' : undefined}
    >
      <div className="flex-shrink-0 mt-0.5 text-ink-2" aria-hidden="true">
        {item.status === 'complete' && <TQCheckIcon />}
        {item.status === 'active'   && <TQRadioIcon />}
        {item.status === 'locked'   && <TQLockIcon />}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-ink">{item.title}</div>
        <div className="text-xs text-ink-placeholder mt-1">
          {tierLabel} · {item.level}
          {item.scored != null && <span> · Scored {item.scored}</span>}
          {item.time   != null && <span> · {item.time}</span>}
        </div>
        {item.note && (
          <div className="text-[11px] font-semibold text-accent-ink mt-1.5">{item.note}</div>
        )}
      </div>
      {item.status === 'active' && (
        <button className="flex-shrink-0 self-center text-xs font-semibold text-bg bg-primary rounded-sm px-3 py-1.5 hover:bg-primary-hover transition duration-fast ease-out-quart">
          Take
        </button>
      )}
    </div>
  );
}
```

> **Fidelity note:** Match exact paddings/colors from the OLD CSS. The values above are the translation; if the old `.tq-item` used different spacing (e.g. `var(--space-3)` gap), use that. Read the old CSS to confirm each value before finalizing.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/shared/TQItem.js
git commit -m "refactor: extract TQItem to shared component (Tailwind)"
```

---

### Task 9: shared/RadarBriefingPanel.js

**Files:**
- Create: `src/components/shared/RadarBriefingPanel.js`

- [ ] **Step 1: Write the component**

Source JSX: `workspace/page.js` lines 900-969. Source CSS: old globals.css `.radar-briefing-grid`, `.briefing-eyebrow`, `.expert-clip-card`, `.clip-play-btn`, `.clip-body`, `.clip-quote`, `.clip-source`, `.clip-waveform`, `.ai-tip-card`, `.ai-tip-icon`, `.ai-tip-text`, `.briefing-header-row`, `.wf-steps`, `.wf-step-card`, `.wf-step-card--done/active/locked`, `.wf-step-card-head/num/icon/title/meta`, `.wf-step-card-badge`, `.briefing-footer`, `.briefing-footer-note`, `.briefing-cta-btn` (≈ lines 2732-2998).

Translate each class to Tailwind. Keep `meeting` prop, `ctaLabel` logic, all `aria-*`/`title` attributes identical. Import `PlayIcon`, `SparkleIcon`, `WFCheckIcon`, `WFLockIcon`, `WaveformViz`, `ChevronRightIcon` from `@/components/icons`.

```js
'use client';

import {
  PlayIcon, SparkleIcon, WFCheckIcon, WFLockIcon, WaveformViz, ChevronRightIcon,
} from '@/components/icons';

export function RadarBriefingPanel({ meeting }) {
  const ctaLabel = meeting.prepStatus === 'cold'
    ? 'Start Step 01'
    : meeting.prepStatus === 'in-progress'
    ? 'Continue Step 02'
    : null;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
      {/* LEFT COLUMN: clip + AI tip — translate .radar-briefing-grid left col */}
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-2 mb-2">
          {meeting.clip.label || 'Expert clip · 2 min'}
        </div>
        {/* expert-clip-card */}
        <div className="flex items-center gap-3 p-3 rounded-md border border-line-subtle bg-surface mb-4">
          <button className="flex-shrink-0 flex items-center justify-center w-8 h-8 rounded-full bg-primary text-bg" aria-label="Play clip">
            <PlayIcon />
          </button>
          <div className="flex-1 min-w-0">
            <div className="text-sm text-ink">&ldquo;{meeting.clip.quote}&rdquo;</div>
            <div className="text-xs text-ink-placeholder mt-1">{meeting.clip.meta}</div>
          </div>
          <div className="flex-shrink-0 text-primary" aria-hidden="true"><WaveformViz /></div>
        </div>

        <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-2 mb-2">
          AI tip · account health
        </div>
        {/* ai-tip-card */}
        <div className="flex gap-2 p-3 rounded-md bg-primary-subtle">
          <div className="flex-shrink-0 text-primary mt-0.5"><SparkleIcon /></div>
          <p className="text-sm text-ink-2 leading-base">{meeting.tip}</p>
        </div>
      </div>

      {/* RIGHT COLUMN: waterfall steps */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-2">Mission Briefing · locked sequence</div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-2">{meeting.industry}</div>
        </div>

        <div className="flex flex-col gap-2">
          {meeting.waterfall.map((step, i) => (
            <div
              key={i}
              className={`p-3 rounded-md border ${
                step.state === 'locked' ? 'border-line-subtle opacity-50'
                : step.state === 'active' ? 'border-primary'
                : 'border-line-subtle'
              }`}
              title={step.state === 'locked' ? (step.meta && step.meta !== 'Locked' ? step.meta : 'Complete the previous step to unlock') : undefined}
              aria-disabled={step.state === 'locked' ? 'true' : undefined}
            >
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-2">
                  Step {String(i + 1).padStart(2, '0')} · {step.kind}
                </span>
                <span className="flex items-center">
                  {step.state === 'done'   && <span className="text-success"><WFCheckIcon /></span>}
                  {step.state === 'locked' && <span className="text-ink-placeholder"><WFLockIcon /></span>}
                  {step.state === 'active' && <span className="text-[10px] font-semibold uppercase text-primary bg-primary-subtle rounded-sm px-1.5 py-0.5">Now</span>}
                </span>
              </div>
              <div className="text-sm font-medium text-ink mt-1">{step.label}</div>
              <div className="text-xs text-ink-placeholder mt-0.5">{step.meta}</div>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between gap-3 mt-4">
          <span className="text-xs text-ink-placeholder">
            Once the waterfall is done, this card flips to <strong>You&apos;re prepped</strong>.
          </span>
          {ctaLabel && (
            <button className="flex-shrink-0 inline-flex items-center gap-1 text-xs font-semibold text-bg bg-primary rounded-sm px-3 py-1.5 hover:bg-primary-hover transition duration-fast ease-out-quart">
              {ctaLabel} <ChevronRightIcon />
            </button>
          )}
          {meeting.prepStatus === 'ready' && (
            <span style={{ fontSize: '11px', color: 'var(--color-success)', fontWeight: 600 }}>✓ Ready to walk in</span>
          )}
        </div>
      </div>
    </div>
  );
}
```

> **Fidelity note:** This is a high-complexity layout. Read the old CSS for the exact grid columns, gaps, clip-card padding, waveform sizing, and step-card border colors. Adjust the utilities above to match pixel-for-pixel before committing.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/shared/RadarBriefingPanel.js
git commit -m "refactor: extract RadarBriefingPanel to shared (Tailwind)"
```

---

### Task 10: shared/RadarRow.js

**Files:**
- Create: `src/components/shared/RadarRow.js`

- [ ] **Step 1: Write the component**

Source JSX: `workspace/page.js` lines 856-898. Source CSS: `.radar-row-wrap`, `.radar-row`, `.radar-row-time`, `.radar-day`, `.radar-clock`, `.radar-relative`, `.radar-row-body`, `.radar-row-title`, `.radar-account`, `.radar-meeting-name`, `.radar-tags`, `.radar-row-actions`, `.radar-prep`, `.radar-prep--ready/progress/cold`, `.radar-briefing-btn`, `.radar-briefing-expand`, `.radar-briefing-inner` (≈ lines 2272-2454 + 2732-2760).

Uses `useState`, the `grid-rows-0fr → grid-rows-1fr` expand pattern, and imports `RadarBriefingPanel`, `ChevronRightIcon`, `ChevronDownIcon`.

```js
'use client';

import { useState } from 'react';
import { RadarBriefingPanel } from '@/components/shared/RadarBriefingPanel';
import { ChevronRightIcon, ChevronDownIcon } from '@/components/icons';

const PREP_CHIP = {
  'ready':       'bg-success-surface text-success',
  'in-progress': 'bg-warning-surface text-warning',
  'cold':        'bg-surface text-ink-placeholder',
};

export function RadarRow({ meeting }) {
  const [open, setOpen] = useState(false);
  const chipClass = PREP_CHIP[meeting.prepStatus] || PREP_CHIP['in-progress'];

  return (
    <div>
      <div
        className="grid grid-cols-[80px_1fr_auto] items-center gap-4 py-3 px-5 cursor-pointer hover:bg-surface transition duration-fast ease-out-quart"
        onClick={() => setOpen(o => !o)}
      >
        <div>
          <div className="text-xs font-semibold text-ink">{meeting.day}</div>
          <div className="text-xs text-ink-2">{meeting.time}</div>
          <div className="text-[11px] text-ink-placeholder">{meeting.relative}</div>
        </div>
        <div>
          <div className="text-sm font-semibold text-ink">
            <span>{meeting.account}</span>
            <span className="text-ink-2 font-medium"> · {meeting.title}</span>
          </div>
          <div className="text-xs text-ink-placeholder mt-0.5">{meeting.tags}</div>
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-[11px] font-semibold uppercase rounded-sm px-2 py-1 ${chipClass}`}>
            {meeting.prepLabel}
          </span>
          <button
            className="inline-flex items-center gap-1 text-xs font-medium text-ink-2 hover:text-ink transition duration-fast ease-out-quart"
            onClick={e => { e.stopPropagation(); setOpen(o => !o); }}
          >
            {open ? <>Hide briefing <ChevronDownIcon /></> : <>Open briefing <ChevronRightIcon /></>}
          </button>
        </div>
      </div>

      <div className={`grid transition-[grid-template-rows] duration-slow ease-out-expo ${open ? 'grid-rows-1fr' : 'grid-rows-0fr'}`}>
        <div className="overflow-hidden min-h-0">
          <div className="py-4 px-5 border-t border-line-subtle">
            <RadarBriefingPanel meeting={meeting} />
          </div>
        </div>
      </div>
    </div>
  );
}
```

> **Fidelity note:** Confirm the prep-chip color mapping against the old `.radar-prep--ready/progress/cold` rules. Confirm the grid column template `80px 1fr auto` matches `.radar-row`.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/shared/RadarRow.js
git commit -m "refactor: extract RadarRow to shared (Tailwind)"
```

---

### Task 11: shared/RadarDeckStack.js

**Files:**
- Create: `src/components/shared/RadarDeckStack.js`

- [ ] **Step 1: Write the component (includes RadarDeckCard + RadarDeckNav)**

Source JSX: `workspace/page.js` lines 681-852. **The radar-deck-card / data-slot / rdc-clickable / rdc-expand classes stay as custom classes** (they're preserved in globals.css Task 3 + the residual rdc-* rules — see note). Keep ALL of these custom classes on the elements; do NOT convert them to Tailwind: `radar-deck-wrap`, `radar-deck-card`, `data-slot`, `is-open`, `rdc-clickable`, `rdc-header`, `rdc-time-row`, `rdc-day/dot/time/relative`, `rdc-title-row`, `rdc-account/sep/meeting-name`, `rdc-meta-row`, `rdc-expand`, `rdc-expand-inner`, `rdc-briefing-wrap`, `rdc-expand-footer`, `rdc-close-btn`, `radar-deck-nav`, `rdn-arrow`, `rdn-counter`, `radar-prep`. The `radar-prep` chip classes also stay.

> **DEPENDENCY:** Task 3 only kept the deck *positioning* CSS (`.radar-deck-wrap`, `.radar-deck-card`, `[data-slot]`, `.deck-is-open`). The inner classes (`.rdc-clickable`, `.rdc-header`, `.rdc-time-row`, `.rdc-day`, `.rdc-expand`, `.rdc-close-btn`, `.radar-deck-nav`, `.rdn-arrow`, `.rdn-counter`, `.radar-prep*`) must ALSO be preserved. **Amend Task 3:** copy the full RADAR DECK STACK block (old globals.css lines ~3360-3634) VERBATIM into globals.css, not just the positioning subset. This keeps the 3D deck pixel-perfect. Do that before this task.

```js
'use client';

import { useState } from 'react';
import { RadarBriefingPanel } from '@/components/shared/RadarBriefingPanel';
import { ChevronLeftIcon, ChevronRightIcon, ChevronUpIcon } from '@/components/icons';

function RadarDeckNav({ activeIndex, total, onPrev, onNext }) {
  return (
    <div className="radar-deck-nav">
      <button className="rdn-arrow rdn-arrow--prev" onClick={onPrev} disabled={activeIndex === 0} aria-label="Previous meeting">
        <ChevronLeftIcon />
      </button>
      <span className="rdn-counter" aria-live="polite">{activeIndex + 1} / {total}</span>
      <button className="rdn-arrow rdn-arrow--next" onClick={onNext} disabled={activeIndex === total - 1} aria-label="Next meeting">
        <ChevronRightIcon />
      </button>
    </div>
  );
}

function RadarDeckCard({ meeting, slot, open, onToggle }) {
  const isFront = slot === 'front';
  const chipClass = meeting ? ({
    'ready':       'radar-prep--ready',
    'in-progress': 'radar-prep--progress',
    'cold':        'radar-prep--cold',
  }[meeting.prepStatus] || 'radar-prep--progress') : '';

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(); }
  };

  if (!meeting) {
    return <div className="radar-deck-card" data-slot={slot} aria-hidden="true" tabIndex={-1} />;
  }

  return (
    <div
      className={`radar-deck-card${open ? ' is-open' : ''}`}
      data-slot={slot}
      aria-hidden={!isFront ? 'true' : undefined}
      tabIndex={isFront ? undefined : -1}
    >
      <div
        className="rdc-clickable"
        onClick={isFront ? onToggle : undefined}
        onKeyDown={isFront ? handleKeyDown : undefined}
        role={isFront ? 'button' : undefined}
        aria-expanded={isFront ? open : undefined}
        tabIndex={isFront ? 0 : -1}
      >
        <div className="rdc-header">
          <div className="rdc-time-row">
            <span className="rdc-day">{meeting.day}</span>
            <span className="rdc-dot" aria-hidden="true">·</span>
            <span className="rdc-time">{meeting.time}</span>
            <span className="rdc-dot" aria-hidden="true">·</span>
            <span className="rdc-relative">{meeting.relative}</span>
          </div>
          <span className={`radar-prep ${chipClass}`}>{meeting.prepLabel}</span>
        </div>
        <div className="rdc-title-row">
          <span className="rdc-account">{meeting.account}</span>
          <span className="rdc-sep" aria-hidden="true"> · </span>
          <span className="rdc-meeting-name">{meeting.title}</span>
        </div>
        <div className="rdc-meta-row">{meeting.industry} · {meeting.tags}</div>
      </div>

      {isFront && (
        <div className="rdc-expand">
          <div className="rdc-expand-inner">
            <div className="rdc-briefing-wrap">
              <RadarBriefingPanel meeting={meeting} />
            </div>
            <div className="rdc-expand-footer">
              <button className="rdc-close-btn" onClick={onToggle} aria-label="Close briefing">
                Close <ChevronUpIcon />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function RadarDeckStack({ meetings }) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [open, setOpen] = useState(false);
  const [navigating, setNavigating] = useState(false);

  const navigate = (newIndex) => {
    if (navigating) return;
    if (open) {
      setNavigating(true);
      setOpen(false);
      setTimeout(() => {
        setActiveIndex(newIndex);
        setNavigating(false);
      }, 360);
    } else {
      setActiveIndex(newIndex);
    }
  };

  const frontMeeting = meetings[activeIndex];
  const midMeeting   = meetings[activeIndex + 1] ?? null;
  const backMeeting  = meetings[activeIndex + 2] ?? null;

  return (
    <div className={`deck-is-open-wrapper${open ? ' deck-is-open' : ''}`}>
      <div className="radar-deck-wrap">
        <RadarDeckCard meeting={backMeeting} slot="back" open={false} onToggle={null} />
        <RadarDeckCard meeting={midMeeting}  slot="mid"  open={false} onToggle={null} />
        <RadarDeckCard meeting={frontMeeting} slot="front" open={open} onToggle={() => setOpen(o => !o)} />
      </div>
      <RadarDeckNav
        activeIndex={activeIndex}
        total={meetings.length}
        onPrev={() => navigate(activeIndex - 1)}
        onNext={() => navigate(activeIndex + 1)}
      />
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/shared/RadarDeckStack.js
git commit -m "refactor: extract RadarDeckStack to shared (custom deck CSS retained)"
```

---

### Task 12: workspace/WorkspaceGreeting.js + NewbieGreeting.js

**Files:**
- Create: `src/components/workspace/WorkspaceGreeting.js`
- Create: `src/components/workspace/NewbieGreeting.js`

- [ ] **Step 1: WorkspaceGreeting.js**

Source JSX: lines 291-307. Source CSS: `.greeting-zone`, `.greeting-top-row`, `.greeting-breadcrumb`, `.greeting-quick-actions`, `.quick-chip`, `.btn`, `.btn-ghost`, `.btn--sm`, `.greeting-heading`, `.greeting-sub` (≈ lines 1955-2057). Convert to Tailwind. No state → still presentational, but keep `'use client'` omitted only if no hooks. (No hooks here → no directive needed, but harmless to omit.)

```js
export function WorkspaceGreeting() {
  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium uppercase tracking-wide text-ink-placeholder">Workspace · Today</span>
        <div className="flex items-center gap-2">
          <button className="text-xs font-medium text-ink-2 bg-surface border border-line rounded-sm px-3 py-1.5 hover:bg-surface-raised transition duration-fast ease-out-quart">Account A · Renewal</button>
          <button className="text-xs font-medium text-ink-2 px-3 py-1.5 rounded-sm hover:bg-surface transition duration-fast ease-out-quart">+ New scratch note</button>
        </div>
      </div>
      <h1 className="text-2xl font-bold text-ink tracking-tight">Good morning, Priya. Two meetings on the deck.</h1>
      <p className="text-sm text-ink-2 mt-2 leading-base">
        The Ego Trap fires every day. Account A renewal is in 2 days — open the briefing in your Radar below.
      </p>
    </div>
  );
}
```

- [ ] **Step 2: NewbieGreeting.js**

Source JSX: lines 491-508.

```js
export function NewbieGreeting() {
  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium uppercase tracking-wide text-ink-placeholder">Workspace · Today</span>
        <div className="flex items-center gap-2">
          <button className="text-xs font-medium text-ink-2 bg-surface border border-line rounded-sm px-3 py-1.5 hover:bg-surface-raised transition duration-fast ease-out-quart">Phase 2 · Understand</button>
          <button className="text-xs font-medium text-ink-2 px-3 py-1.5 rounded-sm hover:bg-surface transition duration-fast ease-out-quart">+ New scratch note</button>
        </div>
      </div>
      <h1 className="text-2xl font-bold text-ink tracking-tight">
        Welcome back, Riya. You&apos;re 41 days into your track.
      </h1>
      <p className="text-sm text-ink-2 mt-2 leading-base">
        Phase 2 of 3 — Understand. Three modules and one Apply simulation queued for today.
      </p>
    </div>
  );
}
```

> **Fidelity note:** Match `.greeting-heading` font-size and `.quick-chip`/`.btn-ghost` exact styling from old CSS.

- [ ] **Step 3: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 4: Commit**

```bash
git add src/components/workspace/WorkspaceGreeting.js src/components/workspace/NewbieGreeting.js
git commit -m "refactor: extract greeting components (Tailwind)"
```

---

### Task 13: workspace/EgoTrapCard.js

**Files:**
- Create: `src/components/workspace/EgoTrapCard.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 311-419. Source CSS: `.et-card`, `.et-header`, `.et-header-left`, `.et-live-dot`, `.et-tag`, `.et-header-meta`, `.et-pill-strip-wrap`, `.et-pill-strip`, `.et-pill`, `.et-pill.is-active`, `.et-body`, `.et-body-row`, `.et-question`, `.et-body-actions`, `.et-mirror-badge`, `.et-view-btn`, `.et-stats`, `.et-mirror-expand`, `.et-mirror-inner`, `.et-mirror-grid`, `.et-mirror-col`, `.et-mirror-col--applied/missed`, `.et-mirror-col-head`, `.et-mirror-col-label`, `.et-mirror-count`, `.et-moments`, `.et-moment-card`, `.et-moment-time`, `.et-moment-quote`, `.et-moment-source`, `.et-mirror-foot`, `.et-mirror-foot-note`, `.et-practice-btn`, `.et-footer`, `.et-footer-sep` (≈ lines 2058-2270 + 2999-3170).

Imports `EGO_TRAPS` from `@/data/workspace`; `ChevronRightIcon`, `ChevronDownIcon`, `ClockIcon`, `WaveIcon`, `PersonIcon` from `@/components/icons`. Uses `useState` for `activeIndex` + `mirrorOpen`. The mirror expand uses `grid-rows-0fr → grid-rows-1fr`. The live dot uses `anim-pulse-dot` (from Task 3).

Translate all classes. Preserve the `et-mirror-col--applied` (success-tinted) vs `et-mirror-col--missed` (warning/accent-tinted) color distinction using `bg-success-surface`/`text-success` and `bg-warning-surface`/`text-warning` respectively (confirm exact tokens against old CSS).

```js
'use client';

import { useState } from 'react';
import { EGO_TRAPS } from '@/data/workspace';
import { ChevronRightIcon, ChevronDownIcon, ClockIcon, WaveIcon, PersonIcon } from '@/components/icons';

export function EgoTrapCard() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [mirrorOpen, setMirrorOpen] = useState(false);
  const trap = EGO_TRAPS[activeIndex];

  const selectTrap = (i) => {
    if (i === activeIndex) return;
    setMirrorOpen(false);
    setActiveIndex(i);
  };

  return (
    <div className="bg-bg border border-line rounded-md shadow-low mb-6 overflow-hidden">
      {/* header */}
      <div className="flex items-center justify-between py-3 px-5 border-b border-line-subtle">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-error anim-pulse-dot" aria-hidden="true" />
          <span className="text-xs font-semibold uppercase tracking-wide text-ink">Ego Trap · Fires every day</span>
        </div>
        <span className="text-[11px] text-ink-placeholder">Generated {trap.generatedAt} · Transcript processed</span>
      </div>

      {/* pill strip */}
      <div className="px-5 pt-4">
        <div className="flex gap-2 overflow-x-auto" role="tablist" aria-label="This week's meetings">
          {EGO_TRAPS.map((t, i) => (
            <button
              key={i}
              role="tab"
              aria-selected={i === activeIndex}
              className={`flex-shrink-0 text-xs font-medium rounded-full px-3 py-1.5 border transition duration-fast ease-out-quart ${
                i === activeIndex ? 'bg-ink text-bg border-ink' : 'bg-surface text-ink-2 border-line hover:bg-surface-raised'
              }`}
              onClick={() => selectTrap(i)}
            >
              {t.day} · {t.account}
            </button>
          ))}
        </div>
      </div>

      {/* body */}
      <div className="py-4 px-5">
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold text-ink leading-snug">{trap.question}</h2>
          <div className="flex items-center gap-3 flex-shrink-0">
            <span className="text-[11px] font-medium uppercase text-ink-placeholder">Mirror · Not a score</span>
            <button className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:text-primary-hover transition duration-fast ease-out-quart" onClick={() => setMirrorOpen(o => !o)}>
              {mirrorOpen ? <>Hide mirror <ChevronDownIcon /></> : <>View mirror <ChevronRightIcon /></>}
            </button>
          </div>
        </div>
        <p className="text-sm text-ink-2 mt-2 leading-base">
          {trap.applied} moments applied · {trap.missed} moments missed
          {' '}· cross-referenced against {trap.modules} modules and {trap.failureStories} failure stories.
        </p>
      </div>

      {/* mirror expand */}
      <div className={`grid transition-[grid-template-rows] duration-slow ease-out-expo ${mirrorOpen ? 'grid-rows-1fr' : 'grid-rows-0fr'}`}>
        <div className="overflow-hidden min-h-0">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 py-4 px-5 border-t border-line-subtle">
            {/* applied col */}
            <div className="rounded-md bg-success-surface p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold uppercase text-success">What you applied</span>
                <span className="text-xs font-semibold text-success">{trap.appliedMoments.length}</span>
              </div>
              <div className="flex flex-col gap-2">
                {trap.appliedMoments.map((m, i) => (
                  <div key={i} className="rounded-md bg-bg border border-line-subtle p-3">
                    <div className="text-[11px] font-semibold text-ink-2">{m.time}</div>
                    <p className="text-sm text-ink mt-1 leading-base">{m.quote}</p>
                    <div className="text-[11px] text-ink-placeholder mt-1">{m.source}</div>
                  </div>
                ))}
              </div>
            </div>
            {/* missed col */}
            <div className="rounded-md bg-warning-surface p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold uppercase text-warning">What you missed</span>
                <span className="text-xs font-semibold text-warning">{trap.missedMoments.length}</span>
              </div>
              <div className="flex flex-col gap-2">
                {trap.missedMoments.map((m, i) => (
                  <div key={i} className="rounded-md bg-bg border border-line-subtle p-3">
                    <div className="text-[11px] font-semibold text-ink-2">{m.time}</div>
                    <p className="text-sm text-ink mt-1 leading-base">{m.quote}</p>
                    <div className="text-[11px] text-ink-placeholder mt-1">{m.source}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between gap-3 py-3 px-5 border-t border-line-subtle">
            <span className="text-xs text-ink-placeholder">
              Full post-mortem on this pattern is in the <strong>Failure Library</strong>.
            </span>
            <button className="inline-flex items-center gap-1 text-xs font-semibold text-bg bg-primary rounded-sm px-3 py-1.5 hover:bg-primary-hover transition duration-fast ease-out-quart">
              Practice in Simulator <ChevronRightIcon />
            </button>
          </div>
        </div>
      </div>

      {/* footer */}
      <div className="flex items-center gap-2 py-3 px-5 border-t border-line-subtle text-[11px] text-ink-placeholder">
        <ClockIcon /><span>{trap.duration}</span>
        <span className="w-px h-3 bg-line mx-1" />
        <WaveIcon /><span>{trap.source}</span>
        <span className="w-px h-3 bg-line mx-1" />
        <PersonIcon /><span>{trap.participants} Participants</span>
      </div>
    </div>
  );
}
```

> **Fidelity note:** This is the most visually intricate veteran card. Read old CSS for: `.et-card` shadow/radius, pill active state, mirror column tints, moment-card styling, footer separator. Match exactly.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/workspace/EgoTrapCard.js
git commit -m "refactor: extract EgoTrapCard (Tailwind)"
```

---

### Task 14: workspace/WeeklyRadarCard.js

**Files:**
- Create: `src/components/workspace/WeeklyRadarCard.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 423-444. Source CSS: `.radar-card`, `.radar-header`, `.radar-header-row`, `.radar-title`, `.radar-status-chips`, `.radar-chip`, `.radar-chip--ready/progress/cold`, `.radar-meta` (≈ lines 2272-2340). Imports `RADAR_MEETINGS` from `@/data/workspace`, `RadarDeckStack` from `@/components/shared/RadarDeckStack`.

```js
'use client';

import { RADAR_MEETINGS } from '@/data/workspace';
import { RadarDeckStack } from '@/components/shared/RadarDeckStack';

export function WeeklyRadarCard() {
  const prepped    = RADAR_MEETINGS.filter(m => m.prepStatus === 'ready').length;
  const inProgress = RADAR_MEETINGS.filter(m => m.prepStatus === 'in-progress').length;
  const cold       = RADAR_MEETINGS.filter(m => m.prepStatus === 'cold').length;

  return (
    <div className="bg-bg border border-line rounded-md shadow-low mb-6">
      <div className="py-4 px-5 border-b border-line-subtle">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-ink">Weekly Radar</h2>
          <div className="flex items-center gap-2">
            {prepped > 0    && <span className="text-[11px] font-semibold uppercase rounded-sm px-2 py-1 bg-success-surface text-success">{prepped} Prepped</span>}
            {inProgress > 0 && <span className="text-[11px] font-semibold uppercase rounded-sm px-2 py-1 bg-warning-surface text-warning">{inProgress} In Progress</span>}
            {cold > 0       && <span className="text-[11px] font-semibold uppercase rounded-sm px-2 py-1 bg-surface text-ink-placeholder">{cold} Cold</span>}
          </div>
        </div>
        <div className="text-xs text-ink-placeholder mt-1">Calendar sync · {RADAR_MEETINGS.length} meetings · Click a card to open briefing</div>
      </div>
      <RadarDeckStack meetings={RADAR_MEETINGS} />
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/workspace/WeeklyRadarCard.js
git commit -m "refactor: extract WeeklyRadarCard (Tailwind)"
```

---

### Task 15: workspace/TestQueuePanel.js

**Files:**
- Create: `src/components/workspace/TestQueuePanel.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 448-465. Source CSS: `.right-panel-section`, `.right-panel-header`, `.right-panel-title`, `.right-panel-meta`, `.right-panel-view-all`, `.tq-list` (≈ lines 2455-2520). Imports `TEST_QUEUE` from `@/data/workspace`, `TQItem` from `@/components/shared/TQItem`.

```js
'use client';

import { TEST_QUEUE } from '@/data/workspace';
import { TQItem } from '@/components/shared/TQItem';

export function TestQueuePanel() {
  const activeTier = TEST_QUEUE.find(i => i.status === 'active')?.tier ?? 1;

  return (
    <div className="bg-bg border border-line rounded-md shadow-low p-4 mb-5">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">Test queue</h3>
          <div className="text-xs text-ink-placeholder mt-0.5">Waterfall · Tier {activeTier} of 3</div>
        </div>
        <button className="text-xs font-medium text-primary hover:text-primary-hover transition duration-fast ease-out-quart">View all</button>
      </div>
      <div className="flex flex-col gap-2">
        {TEST_QUEUE.map(item => <TQItem key={item.id} item={item} tierLabel={`Tier ${item.tier}`} />)}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/workspace/TestQueuePanel.js
git commit -m "refactor: extract TestQueuePanel (Tailwind)"
```

---

### Task 16: workspace/KnowledgeDropsPanel.js

**Files:**
- Create: `src/components/workspace/KnowledgeDropsPanel.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 469-487. Source CSS: `.right-panel-section--drops`, `.drops-new-badge`, `.drops-list`, `.drop-item`, `.drop-type`, `.drop-title` (≈ lines 2600-2676). Imports `KNOWLEDGE_DROPS` from `@/data/workspace`, `ChevronRightIcon` from `@/components/icons`.

```js
'use client';

import { KNOWLEDGE_DROPS } from '@/data/workspace';
import { ChevronRightIcon } from '@/components/icons';

export function KnowledgeDropsPanel() {
  return (
    <div className="bg-bg border border-line rounded-md shadow-low p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-ink">Knowledge drops</h3>
        <span className="text-[11px] font-semibold uppercase rounded-sm px-2 py-0.5 bg-accent-surface text-accent-ink">{KNOWLEDGE_DROPS.length} new</span>
      </div>
      <div className="flex flex-col gap-2">
        {KNOWLEDGE_DROPS.map(d => (
          <button key={d.id} className="flex items-center gap-2 text-left rounded-md border border-line-subtle p-3 hover:bg-surface transition duration-fast ease-out-quart">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-placeholder">{d.type}</span>
            <span className="flex-1 text-sm font-medium text-ink">{d.title}</span>
            <ChevronRightIcon />
          </button>
        ))}
      </div>
    </div>
  );
}
```

> **Fidelity note:** Confirm `.drop-type` vs `.drop-title` layout (the old layout may stack type above title). Match the old CSS.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/workspace/KnowledgeDropsPanel.js
git commit -m "refactor: extract KnowledgeDropsPanel (Tailwind)"
```

---

### Task 17: workspace/NewbieTrackHero.js

**Files:**
- Create: `src/components/workspace/NewbieTrackHero.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 513-587. Source CSS: reuses `.et-card`/`.et-header`/`.et-body`/`.et-mirror-expand`/`.et-footer` PLUS `.track-progress`, `.track-bar`, `.track-bar-fill`, `.track-phases`, `.track-phase`, `.track-phase.done/active`, `.newbie-next-up`, `.newbie-item`, `.newbie-item-kind`, `.newbie-item-body`, `.newbie-item-desc`, `.newbie-item-meta`, `.briefing-eyebrow` (≈ lines 3171-3274). Imports `NEWBIE_TRACK` from `@/data/workspace`; `ChevronRightIcon`, `ChevronDownIcon`, `ClockIcon` from `@/components/icons`. Uses `useState` for `open`. The inline `style={{ marginTop: ... }}` and `style={{ '--reveal-delay' ... }}` and the `track-bar-fill` `style={{ transform: scaleX(...) }}` stay as inline styles.

Convert to Tailwind, keeping the progress-bar `scaleX` transform inline. The expand uses `grid-rows-0fr → grid-rows-1fr`.

```js
'use client';

import { useState } from 'react';
import { NEWBIE_TRACK } from '@/data/workspace';
import { ChevronRightIcon, ChevronDownIcon, ClockIcon } from '@/components/icons';

export function NewbieTrackHero() {
  const [open, setOpen] = useState(false);
  const t = NEWBIE_TRACK;

  return (
    <div className="bg-bg border border-line rounded-md shadow-low mb-6 overflow-hidden">
      <div className="flex items-center justify-between py-3 px-5 border-b border-line-subtle">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-primary anim-pulse-dot" aria-hidden="true" />
          <span className="text-xs font-semibold uppercase tracking-wide text-ink">3-Month Mandatory Track · Phase {t.phase} of {t.totalPhases}</span>
        </div>
        <span className="text-[11px] text-ink-placeholder">Day {t.day} / {t.totalDays} · Bloom: {t.phaseLabel}</span>
      </div>

      <div className="py-4 px-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-ink leading-snug">Phase {t.phase} · {t.phaseLabel} — {t.progress}% complete</h2>
            <p className="text-sm text-ink-2 mt-2 leading-base">
              One module and one case study queued for today. Apply simulations unlock when this phase finishes.
            </p>
          </div>
          <button className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:text-primary-hover transition duration-fast ease-out-quart flex-shrink-0" onClick={() => setOpen(o => !o)}>
            {open ? <>Hide <ChevronDownIcon /></> : <>What&apos;s next <ChevronRightIcon /></>}
          </button>
        </div>

        {/* progress */}
        <div className="mt-4">
          <div className="h-1.5 rounded-full bg-surface-raised overflow-hidden">
            <div className="h-full bg-primary origin-left" style={{ transform: `scaleX(${t.progress / 100})` }} />
          </div>
          <div className="flex justify-between mt-2 text-[11px] text-ink-placeholder">
            <div className="text-ink-2">Phase 1 <b>Remember</b></div>
            <div className="text-ink font-medium">Phase 2 <b>Understand</b></div>
            <div>Phase 3 <b>Apply</b></div>
          </div>
        </div>
      </div>

      <div className={`grid transition-[grid-template-rows] duration-slow ease-out-expo ${open ? 'grid-rows-1fr' : 'grid-rows-0fr'}`}>
        <div className="overflow-hidden min-h-0">
          <div className="py-4 px-5 border-t border-line-subtle">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-2 mb-3">Next up · today</div>
            <div className="flex flex-col gap-3">
              {t.nextUp.map((item, i) => (
                <div key={i} className="flex gap-3">
                  <span className="flex-shrink-0 text-[10px] font-semibold uppercase tracking-wide text-primary bg-primary-subtle rounded-sm px-2 py-1 h-fit">{item.kind}</span>
                  <div>
                    <div className="text-sm text-ink leading-base">{item.desc}</div>
                    <div className="text-xs text-ink-placeholder mt-1">{item.meta}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between gap-3 py-3 px-5 border-t border-line-subtle">
            <span className="text-xs text-ink-placeholder">
              The track <strong>cannot be skipped</strong>. Personalisation unlocks at day {t.totalDays}.
            </span>
            <button className="inline-flex items-center gap-1 text-xs font-semibold text-bg bg-primary rounded-sm px-3 py-1.5 hover:bg-primary-hover transition duration-fast ease-out-quart">
              Resume Phase {t.phase} <ChevronRightIcon />
            </button>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 py-3 px-5 border-t border-line-subtle text-[11px] text-ink-placeholder">
        <ClockIcon /><span>Day {t.day} / {t.totalDays}</span>
        <span className="w-px h-3 bg-line mx-1" />
        <span>Phase {t.phase} of {t.totalPhases}</span>
        <span className="w-px h-3 bg-line mx-1" />
        <span>{t.phaseLabel}</span>
      </div>
    </div>
  );
}
```

> **Fidelity note:** Confirm `.track-bar` height/color and `.track-bar-fill` transition against old CSS.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/workspace/NewbieTrackHero.js
git commit -m "refactor: extract NewbieTrackHero (Tailwind)"
```

---

### Task 18: workspace/NewbieRadarCard.js

**Files:**
- Create: `src/components/workspace/NewbieRadarCard.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 591-628. Source CSS: `.radar-card`, `.radar-header*`, `.radar-meetings`, `.radar-row` (static internal variant), `.radar-prep--internal` (≈ lines 2272-2454). Imports `NEWBIE_RADAR_MEETINGS` from `@/data/workspace`, `RadarRow` from `@/components/shared/RadarRow`. The static internal meeting keeps its inline `style` props (cursor, color).

```js
'use client';

import { NEWBIE_RADAR_MEETINGS } from '@/data/workspace';
import { RadarRow } from '@/components/shared/RadarRow';

export function NewbieRadarCard() {
  return (
    <div className="bg-bg border border-line rounded-md shadow-low mb-6">
      <div className="py-4 px-5 border-b border-line-subtle">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-ink">Your week</h2>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase rounded-sm px-2 py-1 bg-warning-surface text-warning">Mandatory track prep</span>
          </div>
        </div>
        <div className="text-xs text-ink-placeholder mt-1">Your first calls are sit-ins — Aryan is the lead</div>
      </div>

      <div className="divide-y divide-line-subtle">
        {NEWBIE_RADAR_MEETINGS.map(m => <RadarRow key={m.id} meeting={m} />)}

        {/* Static internal meeting */}
        <div className="grid grid-cols-[80px_1fr_auto] items-center gap-4 py-3 px-5" style={{ cursor: 'default' }}>
          <div>
            <div className="text-xs font-semibold text-ink">WED</div>
            <div className="text-xs text-ink-2">3:00 PM</div>
            <div className="text-[11px]" style={{ color: 'var(--color-ink-placeholder)' }}>IN 2 DAYS</div>
          </div>
          <div>
            <div className="text-sm font-semibold text-ink">
              <span>Cohort sync</span>
              <span className="text-ink-2 font-medium"> · Track checkpoint</span>
            </div>
            <div className="text-xs text-ink-placeholder mt-0.5">Internal · weekly cohort review</div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-[11px] font-semibold uppercase rounded-sm px-2 py-1 bg-surface text-ink-placeholder">Internal</span>
          </div>
        </div>
      </div>
    </div>
  );
}
```

> **Fidelity note:** Confirm `.radar-prep--internal` color and whether `.radar-meetings` uses dividers between rows. Match old CSS.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/workspace/NewbieRadarCard.js
git commit -m "refactor: extract NewbieRadarCard (Tailwind)"
```

---

### Task 19: workspace/NewbieTestQueuePanel.js

**Files:**
- Create: `src/components/workspace/NewbieTestQueuePanel.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 632-649.

```js
'use client';

import { NEWBIE_TEST_QUEUE } from '@/data/workspace';
import { TQItem } from '@/components/shared/TQItem';

export function NewbieTestQueuePanel() {
  return (
    <div className="bg-bg border border-line rounded-md shadow-low p-4 mb-5">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">Test queue</h3>
          <div className="text-xs text-ink-placeholder mt-0.5">Fixed · mandatory until day 90</div>
        </div>
        <button className="text-xs font-medium text-primary hover:text-primary-hover transition duration-fast ease-out-quart">View all</button>
      </div>
      <div className="flex flex-col gap-2">
        {NEWBIE_TEST_QUEUE.map(item => (
          <TQItem key={item.id} item={item} tierLabel={`Phase ${item.phase}`} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/workspace/NewbieTestQueuePanel.js
git commit -m "refactor: extract NewbieTestQueuePanel (Tailwind)"
```

---

### Task 20: workspace/BloomCard.js

**Files:**
- Create: `src/components/workspace/BloomCard.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 653-677. Source CSS: `.bloom-card-badge`, `.bloom-stages`, `.bloom-stage`, `.bloom-stage--done/active/next/locked`, `.bloom-stage-indicator`, `.bloom-stage-indicator--done/active/locked`, `.bloom-stage-label`, `.bloom-stage-note` (≈ lines 3275-3359). Imports `BLOOM_STAGES` from `@/data/workspace`; `WFCheckIcon`, `BloomDotIcon`, `WFLockIcon` from `@/components/icons`. The `bloom-stage--active` uses `primary-subtle` background.

```js
'use client';

import { BLOOM_STAGES } from '@/data/workspace';
import { WFCheckIcon, BloomDotIcon, WFLockIcon } from '@/components/icons';

const STAGE_STYLE = {
  done:   { row: '', ind: 'bg-success text-bg' },
  active: { row: 'bg-primary-subtle', ind: 'bg-primary text-bg' },
  next:   { row: '', ind: 'bg-surface-raised text-ink-2' },
  locked: { row: 'opacity-60', ind: 'bg-surface-raised text-ink-placeholder' },
};

export function BloomCard() {
  return (
    <div className="bg-bg border border-line rounded-md shadow-low p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-ink">Bloom&apos;s · your path</h3>
        <span className="text-[11px] font-semibold uppercase rounded-sm px-2 py-0.5 bg-primary-subtle text-primary">Newbie</span>
      </div>
      <div className="flex flex-col gap-2">
        {BLOOM_STAGES.map((stage, i) => {
          const s = STAGE_STYLE[stage.state] || STAGE_STYLE.next;
          return (
            <div key={i} className={`flex items-start gap-3 rounded-md p-2 ${s.row}`}>
              <div className={`flex-shrink-0 flex items-center justify-center w-5 h-5 rounded-full ${s.ind}`}>
                {stage.state === 'done'   && <WFCheckIcon />}
                {stage.state === 'active' && <BloomDotIcon />}
                {stage.state === 'locked' && <WFLockIcon />}
              </div>
              <div>
                <div className="text-sm font-medium text-ink">{stage.label}</div>
                <div className="text-xs text-ink-placeholder">{stage.note}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

> **Fidelity note:** The `next` state renders no icon in the original (only done/active/locked have icons). Confirm indicator sizes and colors against old CSS.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/workspace/BloomCard.js
git commit -m "refactor: extract BloomCard (Tailwind)"
```

---

### Task 21: Rewrite workspace/page.js to shell

**Files:**
- Modify: `src/app/workspace/page.js`

- [ ] **Step 1: Replace the entire file**

```js
'use client';

import { useMode } from '@/hooks/useMode';
import { WorkspaceGreeting } from '@/components/workspace/WorkspaceGreeting';
import { NewbieGreeting } from '@/components/workspace/NewbieGreeting';
import { EgoTrapCard } from '@/components/workspace/EgoTrapCard';
import { NewbieTrackHero } from '@/components/workspace/NewbieTrackHero';
import { WeeklyRadarCard } from '@/components/workspace/WeeklyRadarCard';
import { NewbieRadarCard } from '@/components/workspace/NewbieRadarCard';
import { TestQueuePanel } from '@/components/workspace/TestQueuePanel';
import { NewbieTestQueuePanel } from '@/components/workspace/NewbieTestQueuePanel';
import { KnowledgeDropsPanel } from '@/components/workspace/KnowledgeDropsPanel';
import { BloomCard } from '@/components/workspace/BloomCard';

export default function WorkspacePage() {
  const mode = useMode();

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_var(--right-panel-width)] gap-6 max-w-content mx-auto py-8 px-8">
      <div className="min-w-0">
        {mode === 'newbie' ? <NewbieGreeting /> : <WorkspaceGreeting />}
        {mode === 'newbie' ? <NewbieTrackHero /> : <EgoTrapCard />}
        {mode === 'newbie' ? <NewbieRadarCard /> : <WeeklyRadarCard />}
      </div>
      <aside className="min-w-0">
        {mode === 'newbie' ? <NewbieTestQueuePanel /> : <TestQueuePanel />}
        {mode === 'newbie' ? <BloomCard /> : <KnowledgeDropsPanel />}
      </aside>
    </div>
  );
}
```

> **Fidelity note:** The old `.workspace-body` / `.workspace-main` / `.workspace-right` grid (≈ globals.css lines 1955-2010) defines the page's max-width, column gap, and right-panel width. Read it and match the grid template + padding exactly. The above is the expected shape; adjust the column ratio/padding to the old values.

- [ ] **Step 2: Verify build + visual**

Run: `npm run build` then `npm run dev` and open `http://localhost:3000/workspace`.
Expected: build passes. Workspace renders in both Veteran and Newbie modes, visually matching the pre-migration app. Toggle mode in the topbar — both layouts and the expand/collapse animations (ego-trap mirror, radar deck, newbie track) work.

- [ ] **Step 3: Commit**

```bash
git add src/app/workspace/page.js
git commit -m "refactor: reduce workspace/page.js to composition shell"
```

---

### Task 22: library/SpotlightCard.js + ModuleCard.js

**Files:**
- Create: `src/components/library/SpotlightCard.js`
- Create: `src/components/library/ModuleCard.js`

- [ ] **Step 1: SpotlightCard.js**

Source JSX: `library/page.js` lines 268-290. Source CSS: `.lib-spotlight`, `.lib-spotlight-badge`, `.lib-spotlight-title`, `.lib-spotlight-desc`, `.lib-spotlight-meta`, `.lib-spotlight-stat`, `.lib-spotlight-dot`, `.lib-spotlight-tags`, `.chip`, `.chip--not-started`, `.btn`, `.btn-primary`, `.btn--sm`, `.lib-spotlight-cta` (≈ lines 3700-3900). Imports `StarIcon`. The spotlight uses `lib-spotlight-enter` keyframe — apply via inline class `animate-[lib-spotlight-enter_...]` OR keep a residual `.lib-spotlight` animation rule. Simplest: keep one residual rule `.anim-spotlight { animation: lib-spotlight-enter ...; }` in globals.css (add in Task 3 keyframes section) and apply `anim-spotlight`.

```js
import { StarIcon } from '@/components/icons';

export function SpotlightCard({ course }) {
  return (
    <div className="anim-spotlight bg-primary-surface border border-line rounded-lg p-6 mb-8">
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-primary mb-3">
        <StarIcon />
        Recommended for you
      </span>
      <h2 className="text-xl font-bold text-ink tracking-tight">{course.title}</h2>
      <p className="text-sm text-ink-2 mt-2 leading-base max-w-content">{course.desc}</p>
      <div className="flex items-center gap-2 mt-3 text-xs text-ink-placeholder">
        <span>{course.modules} modules</span>
        <span>·</span>
        <span>{course.readTime}</span>
      </div>
      <div className="flex flex-wrap gap-2 mt-3">
        {course.tags.map(tag => (
          <span key={tag} className="text-[11px] font-medium rounded-full px-2.5 py-1 bg-surface border border-line text-ink-2">{tag}</span>
        ))}
      </div>
      <button className="mt-4 text-xs font-semibold text-bg bg-primary rounded-sm px-4 py-2 hover:bg-primary-hover transition duration-fast ease-out-quart">Start module</button>
    </div>
  );
}
```

- [ ] **Step 2: ModuleCard.js**

Source JSX: lines 294-306. Source CSS: `.lib-card`, `.lib-card-title`, `.lib-card-desc`, `.lib-card-tags`. `role="button" tabIndex={0}` preserved.

```js
export function ModuleCard({ course }) {
  return (
    <div className="bg-bg border border-line rounded-md p-4 hover:shadow-ambient hover:border-primary transition duration-base ease-out-quart cursor-pointer" role="button" tabIndex={0}>
      <h3 className="text-sm font-semibold text-ink">{course.title}</h3>
      <p className="text-xs text-ink-2 mt-1 leading-base">{course.desc}</p>
      <div className="flex flex-wrap gap-1.5 mt-3">
        {course.tags.map(tag => (
          <span key={tag} className="text-[11px] font-medium rounded-full px-2.5 py-1 bg-surface border border-line text-ink-2">{tag}</span>
        ))}
      </div>
    </div>
  );
}
```

> The `chip chip--not-started` styling must match across SpotlightCard, ModuleCard, and both modals. Read old `.chip`/`.chip--not-started` and use one consistent utility string.

- [ ] **Step 3: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 4: Commit**

```bash
git add src/components/library/SpotlightCard.js src/components/library/ModuleCard.js
git commit -m "refactor: extract SpotlightCard + ModuleCard (Tailwind)"
```

---

### Task 23: library/CourseSection.js + CoursesTab.js

**Files:**
- Create: `src/components/library/CourseSection.js`
- Create: `src/components/library/CoursesTab.js`

- [ ] **Step 1: CourseSection.js**

Source JSX: lines 310-324. Source CSS: `.lib-section`, `.lib-section-header`, `.lib-section-title`, `.btn-text`, `.lib-section-viewall`, `.lib-grid`. The header uses the `lib-reveal` keyframe with `--reveal-delay` inline custom prop. Keep `.lib-section-header` as a residual class with the reveal animation (add `.lib-section-header { animation: lib-reveal 480ms var(--ease-out-quart) both; animation-delay: var(--reveal-delay, 0ms); }` to globals.css Task 3) OR replicate via inline. Simplest & faithful: keep `lib-section-header` residual class. Keep the inline `style={{ '--reveal-delay': ... }}`.

```js
import { ModuleCard } from '@/components/library/ModuleCard';

export function CourseSection({ title, courses, revealDelay }) {
  return (
    <div className="mb-8">
      <div className="lib-section-header flex items-center justify-between mb-3" style={{ '--reveal-delay': `${revealDelay}ms` }}>
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        <button className="text-xs font-medium text-primary hover:text-primary-hover transition duration-fast ease-out-quart">View all</button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {courses.map(course => (
          <ModuleCard key={course.id} course={course} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: CoursesTab.js**

Source JSX: lines 328-342.

```js
import { SPOTLIGHT, COURSE_SECTIONS } from '@/data/library';
import { SpotlightCard } from '@/components/library/SpotlightCard';
import { CourseSection } from '@/components/library/CourseSection';

export function CoursesTab({ mode }) {
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
```

> **Fidelity note:** Confirm `.lib-grid` column count (the old CSS may use `repeat(auto-fill, minmax(...))` — match it; the `md/lg` breakpoints above are an approximation).

- [ ] **Step 3: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 4: Commit**

```bash
git add src/components/library/CourseSection.js src/components/library/CoursesTab.js
git commit -m "refactor: extract CourseSection + CoursesTab (Tailwind)"
```

---

### Task 24: library/CaseStudyCard.js

**Files:**
- Create: `src/components/library/CaseStudyCard.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 346-406. Source CSS: `.lib-cs-card`, `.lib-cs-spark`, `.lib-cs-acct`, `.lib-cs-drop`, `.lib-cs-drop-dot`, `.lib-cs-bars`, `.lib-cs-bar`, `.lib-cs-bar.is-latest/is-recent`, `.lib-cs-sector`, `.lib-cs-body`, `.lib-cs-title`, `.lib-cs-meta`, `.lib-cs-progress`, `.lib-cs-seg`, `.lib-cs-seg.is-filled/is-current`, `.lib-cs-foot`, `.lib-cs-people` (≈ lines 3950-4150). Imports `csBars` from `@/data/library`, `PeopleIcon` from `@/components/icons`. Bars keep inline `style={{ height: ... }}`. The drop-dot uses pulse animation → `anim-pulse-dot`. The bar `is-latest`/`is-recent` color states should be expressed with conditional Tailwind classes (latest = `bg-primary`, recent = `bg-primary/50`, base = `bg-line` — confirm against old CSS).

```js
import { csBars } from '@/data/library';
import { PeopleIcon } from '@/components/icons';

export function CaseStudyCard({ cs, onOpen }) {
  const written = cs.chapters.length;
  const bars = csBars(cs.account + cs.headline);
  const lastIdx = bars.length - 1;

  return (
    <button className="text-left bg-bg border border-line rounded-md overflow-hidden hover:shadow-ambient hover:border-primary transition duration-base ease-out-quart" onClick={() => onOpen(cs)}>
      <div className="relative flex items-end gap-0.5 h-24 bg-surface p-3" aria-hidden="true">
        <span className="absolute top-3 left-3 text-xs font-semibold text-ink">{cs.account}</span>
        {cs.justDropped && (
          <span className="absolute top-3 right-3 inline-flex items-center gap-1 text-[10px] font-semibold uppercase text-primary">
            <span className="w-1.5 h-1.5 rounded-full bg-primary anim-pulse-dot" />
            Chapter just dropped
          </span>
        )}
        <div className="flex items-end gap-0.5 w-full h-full pt-6">
          {bars.map((h, i) => {
            const isLatest = cs.status === 'live' && i === lastIdx;
            const isRecent = !isLatest && i >= lastIdx - 3;
            return (
              <span
                key={i}
                className={`flex-1 rounded-sm ${isLatest ? 'bg-primary' : isRecent ? 'bg-primary/50' : 'bg-line'}`}
                style={{ height: `${h}%` }}
              />
            );
          })}
        </div>
        <span className="absolute bottom-3 right-3 text-[10px] font-medium uppercase text-ink-placeholder">{cs.sector}</span>
      </div>

      <div className="p-4">
        <h3 className="text-sm font-semibold text-ink leading-snug">{cs.headline}</h3>
        <div className="text-xs text-ink-placeholder mt-1">
          {cs.sector} · {cs.region} · {cs.monthsActive} months active
        </div>
        <div className="flex gap-1 mt-3" aria-hidden="true">
          {Array.from({ length: cs.total }).map((_, i) => {
            const filled = i < written;
            const current = cs.justDropped && i === written - 1;
            return (
              <span
                key={i}
                className={`h-1 flex-1 rounded-full ${current ? 'bg-primary' : filled ? 'bg-primary/60' : 'bg-surface-raised'}`}
              />
            );
          })}
        </div>
        <div className="flex items-center justify-between mt-3 text-xs text-ink-placeholder">
          <span>Chapters · {written} of {cs.total} · {cs.status === 'live' ? 'Live' : 'Historical'}</span>
          <span className="inline-flex items-center gap-1">
            <PeopleIcon />
            {cs.participants}
          </span>
        </div>
      </div>
    </button>
  );
}
```

> **Fidelity note:** The sparkline bar colors and progress-segment colors are visually important. Read old `.lib-cs-bar.is-latest`, `.is-recent`, `.lib-cs-seg.is-filled`, `.is-current` and match the exact token/opacity. The `bg-primary/50` arbitrary opacity may need to be a specific token.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/library/CaseStudyCard.js
git commit -m "refactor: extract CaseStudyCard (Tailwind)"
```

---

### Task 25: library/CaseStudyModal.js

**Files:**
- Create: `src/components/library/CaseStudyModal.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 410-475. Source CSS: `.lib-modal-backdrop`, `.lib-modal`, `.lib-modal-header`, `.lib-modal-title`, `.lib-modal-quarter`, `.lib-modal-close`, `.lib-modal-divider`, `.lib-cs-modal-chapters`, `.lib-cs-chapter`, `.lib-cs-chnum`, `.lib-cs-chtitle`, `.lib-cs-chsummary`, `.chip` (≈ lines 4292-4422). **Keep the full focus-trap `useEffect` and `createPortal` exactly.** The backdrop uses `lib-backdrop-enter`, modal uses `lib-modal-enter` keyframe — apply via residual classes `.anim-backdrop` / `.anim-modal` (add to globals.css Task 3) or inline `animate-`. Use residual classes for fidelity.

```js
'use client';

import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

export function CaseStudyModal({ cs, onClose }) {
  const modalRef = useRef(null);

  useEffect(() => {
    const el = modalRef.current;
    if (!el) return;

    const focusable = el.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    first?.focus();

    const onKey = (e) => {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.key !== 'Tab') return;
      if (e.shiftKey) {
        if (document.activeElement === first) { e.preventDefault(); last?.focus(); }
      } else {
        if (document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const written = cs.chapters.length;

  return createPortal(
    <div className="anim-backdrop fixed inset-0 z-modal-backdrop flex items-center justify-center p-4" style={{ background: 'oklch(0 0 0 / 0.48)' }} onClick={onClose}>
      <div
        className="anim-modal relative z-modal w-full max-w-[600px] max-h-[calc(100vh-var(--space-12))] overflow-y-auto bg-bg border border-line rounded-lg shadow-ambient p-6"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="cs-modal-title"
        ref={modalRef}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <span className="text-[11px] font-medium rounded-full px-2.5 py-1 bg-surface border border-line text-ink-2">{cs.account}</span>
            <h2 className="text-xl font-bold text-ink tracking-tight mt-2" id="cs-modal-title">{cs.headline}</h2>
            <span className="block text-xs text-ink-placeholder mt-1">
              {cs.context} · {written} of {cs.total} chapters written
            </span>
          </div>
          <button className="flex-shrink-0 text-lg text-ink-placeholder hover:text-ink transition duration-fast ease-out-quart" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="border-t border-line-subtle my-4" />
        <div className="flex flex-col gap-4">
          {cs.chapters.map(ch => (
            <div key={ch.num} className="flex gap-3">
              <span className="flex-shrink-0 text-[11px] font-semibold uppercase text-primary">Ch {ch.num}</span>
              <div>
                <div className="text-sm font-semibold text-ink">{ch.title}</div>
                <div className="text-sm text-ink-2 mt-1 leading-base">{ch.summary}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>,
    document.body
  );
}
```

> **Fidelity note:** Confirm modal max-width (600px), max-height `calc(100vh - var(--space-12))`, and backdrop opacity `0.48` against old CSS. Keep these exact.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/library/CaseStudyModal.js
git commit -m "refactor: extract CaseStudyModal (Tailwind, focus-trap preserved)"
```

---

### Task 26: library/CaseStudiesTab.js

**Files:**
- Create: `src/components/library/CaseStudiesTab.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 479-494. Source CSS: `.lib-cs-intro`, `.lib-cs-grid`.

```js
'use client';

import { useState } from 'react';
import { CASE_STUDIES } from '@/data/library';
import { CaseStudyCard } from '@/components/library/CaseStudyCard';
import { CaseStudyModal } from '@/components/library/CaseStudyModal';

export function CaseStudiesTab() {
  const [open, setOpen] = useState(null);
  return (
    <div>
      <p className="text-sm text-ink-2 mb-5 leading-base max-w-content">
        Accounts told in chapters as they evolve — both new and existing. Open one to read the full arc.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {CASE_STUDIES.map(cs => (
          <CaseStudyCard key={cs.id} cs={cs} onOpen={setOpen} />
        ))}
      </div>
      {open && <CaseStudyModal cs={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
```

> **Fidelity note:** Confirm `.lib-cs-grid` column template against old CSS.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/library/CaseStudiesTab.js
git commit -m "refactor: extract CaseStudiesTab (Tailwind)"
```

---

### Task 27: library/FailureCard.js

**Files:**
- Create: `src/components/library/FailureCard.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 498-518. Source CSS: `.lib-fl-card`, `.lib-fl-top`, `.lib-fl-cat`, `.lib-fl-cat-dot`, `.lib-fl-quarter`, `.lib-fl-deal`, `.lib-fl-lesson`, `.lib-fl-foot`, `.lib-fl-readmore`, `.lib-fl-readmore-arrow` (≈ lines 4150-4292). Imports `ArrowIcon`. The arrow hover-translate uses `.lib-fl-readmore-arrow` — keep that class residual (add `.lib-fl-card:hover .lib-fl-readmore-arrow { transform: translateX(3px); }` to globals.css) OR use Tailwind group-hover. **Use group-hover** for cleanliness: add `group` to the card and `group-hover:translate-x-1` to the arrow. But `ArrowIcon` hardcodes its own className — change ArrowIcon usage: wrap or pass className. Simplest faithful approach: keep `lib-fl-readmore-arrow` class on ArrowIcon (it already has it) and add the residual hover rule to globals.css. Add to Task 3: `.lib-fl-card:hover .lib-fl-readmore-arrow { transform: translateX(3px); } .lib-fl-readmore-arrow { transition: transform var(--dur-fast) var(--ease-out-quart); }`

```js
import { ArrowIcon } from '@/components/icons';

export function FailureCard({ deal, category, lesson, quarter, entry, onOpen }) {
  return (
    <button className="lib-fl-card text-left bg-bg border border-line rounded-md p-4 hover:shadow-ambient hover:border-primary transition duration-base ease-out-quart" onClick={() => onOpen(entry)}>
      <div className="flex items-center justify-between">
        <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-error">
          <span className="w-1.5 h-1.5 rounded-full bg-error" />
          {category}
        </span>
        <span className="text-[11px] text-ink-placeholder">{quarter}</span>
      </div>
      <div className="text-sm font-semibold text-ink mt-2">{deal}</div>
      <p className="text-xs text-ink-2 mt-1 leading-base">{lesson}</p>
      <div className="flex items-center justify-between mt-3">
        <span className="text-[11px] text-ink-placeholder">Post-mortem</span>
        <span className="inline-flex items-center gap-1 text-xs font-medium text-primary">
          Read <ArrowIcon />
        </span>
      </div>
    </button>
  );
}
```

> **Fidelity note:** Confirm `.lib-fl-cat` / `.lib-fl-cat-dot` color (error/red family) against old CSS.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/library/FailureCard.js
git commit -m "refactor: extract FailureCard (Tailwind)"
```

---

### Task 28: library/FailureModal.js

**Files:**
- Create: `src/components/library/FailureModal.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 522-580. Same modal CSS as CaseStudyModal plus `.lib-modal-section`, `.lib-modal-label`, `.lib-modal-text`, `.lib-modal-text--lead`. Keep focus-trap + createPortal identical.

```js
'use client';

import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

export function FailureModal({ entry, onClose }) {
  const modalRef = useRef(null);

  useEffect(() => {
    const el = modalRef.current;
    if (!el) return;

    const focusable = el.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    first?.focus();

    const onKey = (e) => {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.key !== 'Tab') return;
      if (e.shiftKey) {
        if (document.activeElement === first) { e.preventDefault(); last?.focus(); }
      } else {
        if (document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return createPortal(
    <div className="anim-backdrop fixed inset-0 z-modal-backdrop flex items-center justify-center p-4" style={{ background: 'oklch(0 0 0 / 0.48)' }} onClick={onClose}>
      <div
        className="anim-modal relative z-modal w-full max-w-[600px] max-h-[calc(100vh-var(--space-12))] overflow-y-auto bg-bg border border-line rounded-lg shadow-ambient p-6"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="fl-modal-title"
        ref={modalRef}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <span className="text-[11px] font-medium rounded-full px-2.5 py-1 bg-surface border border-line text-ink-2">{entry.category}</span>
            <h2 className="text-xl font-bold text-ink tracking-tight mt-2" id="fl-modal-title">{entry.deal}</h2>
            <span className="block text-xs text-ink-placeholder mt-1">{entry.quarter}</span>
          </div>
          <button className="flex-shrink-0 text-lg text-ink-placeholder hover:text-ink transition duration-fast ease-out-quart" onClick={onClose} aria-label="Close modal">✕</button>
        </div>
        <div className="border-t border-line-subtle my-4" />
        <div className="mb-5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-2 mb-2">The Lesson</div>
          <p className="text-base text-ink leading-base font-medium">{entry.lesson}</p>
        </div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-2 mb-2">What Happened</div>
          <p className="text-sm text-ink-2 leading-relaxed">{entry.fullPostMortem}</p>
        </div>
      </div>
    </div>,
    document.body
  );
}
```

> **Fidelity note:** `.lib-modal-text--lead` is larger/heavier than `.lib-modal-text`. Confirm sizes against old CSS.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/library/FailureModal.js
git commit -m "refactor: extract FailureModal (Tailwind, focus-trap preserved)"
```

---

### Task 29: library/FailureLibraryTab.js

**Files:**
- Create: `src/components/library/FailureLibraryTab.js`

- [ ] **Step 1: Write the component**

Source JSX: lines 584-602. Source CSS: `.lib-fl-intro`, `.lib-fl-grid`.

```js
import { FAILURE_LIBRARY } from '@/data/library';
import { FailureCard } from '@/components/library/FailureCard';

export function FailureLibraryTab({ onOpen }) {
  return (
    <div>
      <p className="text-sm text-ink-2 mb-5 leading-base max-w-content">
        Post-mortems of churned and lost deals, annotated for what could have changed the outcome.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
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
```

> **Fidelity note:** Confirm `.lib-fl-grid` column template.

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add src/components/library/FailureLibraryTab.js
git commit -m "refactor: extract FailureLibraryTab (Tailwind)"
```

---

### Task 30: Rewrite library/page.js to shell

**Files:**
- Modify: `src/app/library/page.js`

- [ ] **Step 1: Replace the entire file**

Source JSX: lines 604-650. Source CSS: `.lib-page`, `.lib-header`, `.lib-header-title`, `.lib-header-meta`, `.lib-tabs`, `.lib-tab`, `.lib-tab.is-active`, `.lib-content` (uses `lib-content-enter` keyframe on `key={activeTab}` remount). Keep the `key={activeTab}` on the content div so the enter animation re-fires on tab switch. Apply the content-enter animation via residual class `.anim-content-enter` (add to globals.css Task 3) on the content wrapper.

```js
'use client';

import { useState } from 'react';
import { useMode } from '@/hooks/useMode';
import { CoursesTab } from '@/components/library/CoursesTab';
import { CaseStudiesTab } from '@/components/library/CaseStudiesTab';
import { FailureLibraryTab } from '@/components/library/FailureLibraryTab';
import { FailureModal } from '@/components/library/FailureModal';

const TABS = [
  { id: 'courses', label: 'Courses' },
  { id: 'case-studies', label: 'Case Studies' },
  { id: 'failure-library', label: 'Failure Library' },
];

export default function Library() {
  const mode = useMode();
  const [activeTab, setActiveTab] = useState('courses');
  const [openModal, setOpenModal] = useState(null);

  return (
    <div className="py-8 px-8 pb-16 w-full max-w-content mx-auto">
      <header className="flex items-baseline justify-between mb-5">
        <h1 className="text-2xl font-bold text-ink tracking-tight">The Library</h1>
        <span className="text-xs text-ink-placeholder">
          Filtered for {mode === 'veteran' ? 'Veteran' : 'Newbie'}
        </span>
      </header>

      <nav className="flex gap-1 border-b border-line mb-6" aria-label="Library sections">
        {TABS.map(tab => (
          <button
            key={tab.id}
            className={`text-sm font-medium px-4 py-2.5 -mb-px border-b-2 transition duration-fast ease-out-quart ${
              activeTab === tab.id ? 'border-primary text-ink' : 'border-transparent text-ink-2 hover:text-ink'
            }`}
            onClick={() => setActiveTab(tab.id)}
            aria-current={activeTab === tab.id ? 'page' : undefined}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <div className="anim-content-enter" key={activeTab}>
        {activeTab === 'courses' && <CoursesTab mode={mode} />}
        {activeTab === 'case-studies' && <CaseStudiesTab />}
        {activeTab === 'failure-library' && <FailureLibraryTab onOpen={setOpenModal} />}
      </div>

      {openModal && (
        <FailureModal entry={openModal} onClose={() => setOpenModal(null)} />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify build + visual**

Run: `npm run build` then `npm run dev`, open `http://localhost:3000/library`.
Expected: build passes. All three tabs render; tab switch fires the enter animation; case-study cards open the modal (focus trap + Escape work); failure cards open the failure modal; mode label updates with topbar mode switch.

- [ ] **Step 3: Commit**

```bash
git add src/app/library/page.js
git commit -m "refactor: reduce library/page.js to tab shell"
```

---

### Task 31: Migrate AppShell.js to Tailwind

**Files:**
- Modify: `src/components/AppShell.js`

- [ ] **Step 1: Update imports and remove inline icon definitions**

At the top, import icons from the new module and `useMode` is NOT needed here (AppShell manages its own `mode` state via localStorage directly — keep AppShell's own state logic). Replace the icon import section:

```js
'use client';

import { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  MenuIcon, SearchIcon, BellIcon, BellSmIcon, ChatIcon, SunIcon, MoonIcon, BookmarkIcon,
} from '@/components/icons';
```

Delete the entire `/* ── ICONS ── */` block at the bottom of AppShell.js (lines 257-343) — those icons now live in `@/components/icons`.

- [ ] **Step 2: Convert all className custom classes to Tailwind**

Source CSS: old globals.css sidebar block (≈ 1434-1670) and topbar block (≈ 1671-1955). Convert each custom class on every element. The structural classes that need conversion: `app-layout`, `sidebar-collapsed`, `app-sidebar`, `sidebar-org`, `sidebar-org-logo`, `sidebar-org-text`, `sidebar-org-name`, `sidebar-org-ver`, `sidebar-nav`, `sidebar-section-label`, `sidebar-item`, `sidebar-item.is-active`, `sidebar-item-dot`, `sidebar-item-label`, `sidebar-item-shortcut`, `sidebar-today-section`, `sidebar-badge`, `sidebar-spacer`, `sidebar-user`, `sidebar-user-avatar`, `sidebar-user-info`, `sidebar-user-name`, `sidebar-user-meta`, `app-content-zone`, `app-topbar`, `sidebar-toggle-btn`, `topbar-search`, `topbar-search-input`, `topbar-oracle-live`, `oracle-live-dot`, `oracle-live-label`, `topbar-kbd`, `oracle-dropdown`, `oracle-dropdown-label`, `oracle-empty`, `oracle-empty-title`, `oracle-empty-hint`, `oracle-result`, `oracle-result-q`, `oracle-result-cat`, `oracle-dropdown-footer`, `topbar-controls`, `mode-switcher`, `mode-btn`, `mode-btn.is-active`, `topbar-notif-btn`, `app-main`.

> **CRITICAL — the sidebar collapse animation:** The `.app-layout` uses `grid-template-columns: var(--sidebar-width) 1fr` transitioning to `0px 1fr` when `.sidebar-collapsed`. This grid + transition cannot be cleanly expressed inline. **Keep `app-layout`, `sidebar-collapsed`, and `app-sidebar` as residual classes in globals.css** (copy lines ~1404-1432 + the sidebar sticky positioning into the Task 3 residual section). Convert everything *inside* to Tailwind. This is the one AppShell structural exception, mirroring the radar-deck decision.

Amend Task 3 (or do it now): add to globals.css:

```css
/* App layout grid — sidebar collapse transition can't be inline */
.app-layout {
  display: grid;
  grid-template-columns: var(--sidebar-width) 1fr;
  min-height: 100vh;
  transition: grid-template-columns var(--dur-slow) var(--ease-out-expo);
}
.app-layout.sidebar-collapsed { grid-template-columns: 0px 1fr; }
.app-layout.sidebar-collapsed .app-sidebar { border-right-color: transparent; }
.app-sidebar {
  background: var(--sb-bg);
  border-right: 1px solid var(--sb-border);
  display: flex;
  flex-direction: column;
  height: 100vh;
  position: sticky;
  top: 0;
  overflow: hidden;
}
```

Then convert the inner sidebar/topbar elements to Tailwind utilities (using `sb-*` color tokens for sidebar elements, e.g. `text-sb-ink-2`, `bg-sb-active-bg`). Keep `app-layout`/`sidebar-collapsed`/`app-sidebar` classes on the outer elements; everything else becomes Tailwind.

Example conversions (apply the pattern throughout — read old CSS for exact values):
- `<aside className="app-sidebar">` → keep `app-sidebar` (residual)
- `<div className="sidebar-org">` → `<div className="flex items-center gap-3 px-4 py-4 border-b border-sb-border">`
- `<div className="sidebar-org-logo">` → `<div className="flex items-center justify-center w-8 h-8 rounded-md bg-primary text-bg text-xs font-bold">`
- `className={`sidebar-item${active ? ' is-active' : ''}`}` → `className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm text-sb-ink-2 hover:bg-sb-hover-bg transition duration-fast ease-out-quart ${active ? 'bg-sb-active-bg text-sb-ink font-medium' : ''}`}`
- `<div className="app-content-zone">` → `<div className="flex flex-col min-h-screen min-w-0 bg-surface">`
- `<header className="app-topbar">` → `<header className="flex items-center gap-3 h-[var(--topbar-height)] px-4 border-b border-line bg-bg sticky top-0 z-sticky">`
- `className={`mode-btn${mode === 'veteran' ? ' is-active' : ''}`}` → `className={`inline-flex items-center h-7 px-3 text-xs font-medium transition duration-fast ease-out-quart ${mode === 'veteran' ? 'bg-ink text-bg' : 'text-ink-2 hover:bg-surface'}`}`
- `<div className="mode-switcher">` → `<div className="flex items-center border border-line rounded-md overflow-hidden">`
- `oracle-live-dot` → include `anim-pulse-dot` for the pulse
- `<main className="app-main">` → `<main className="flex-1 pt-0">`

> **Fidelity note:** This is the highest-surface conversion. Work element-by-element against the old sidebar/topbar CSS. Pay attention to: oracle dropdown absolute positioning + `z-dropdown` + shadow + `oracle-drop` animation (apply `anim-oracle-drop` residual class or `animate-`), `topbar-search` flex-grow and focus-within border, `sidebar-badge` pill, `sidebar-spacer` (flex-1), kbd styling.

- [ ] **Step 3: Verify build + full visual sweep**

Run: `npm run build` then `npm run dev`.
Expected: build passes. Verify: sidebar renders + collapse toggle animates the grid; nav active states; oracle search dropdown opens/filters/closes on outside-click + Escape; mode switcher toggles (and propagates to workspace/library via CustomEvent); theme toggle switches dark mode (data-theme on documentElement) and all `sb-*`/token colors flip; notifications button renders.

- [ ] **Step 4: Commit**

```bash
git add src/components/AppShell.js src/app/globals.css
git commit -m "refactor: migrate AppShell to Tailwind (layout grid retained)"
```

---

### Task 32: Final verification — build, lint, visual parity

**Files:**
- None (verification only)

- [ ] **Step 1: Production build**

Run:
```bash
npm run build
```
Expected: `✓ Compiled successfully`, all routes (`/`, `/workspace`, `/library`, `/simulator`) listed, no errors.

- [ ] **Step 2: Lint**

Run:
```bash
npm run lint
```
Expected: `✔ No ESLint warnings or errors`. Fix any unused-import or `react/no-unescaped-entities` issues introduced during extraction.

- [ ] **Step 3: Check globals.css size**

Run:
```bash
grep -c "" src/app/globals.css
```
Expected: well under 300 lines (tokens + base + utilities + radar-deck + app-layout + keyframes + residual anim classes). Original was 3,844.

- [ ] **Step 4: Visual parity sweep (dev server)**

Run `npm run dev`. Walk through:
- Workspace · Veteran: greeting, ego-trap card (switch pills, open/close mirror), weekly radar deck (next/prev, open/close briefing), test queue, knowledge drops.
- Workspace · Newbie: greeting, track hero (open/close what's-next, progress bar), newbie radar (open/close row briefing, internal row), newbie test queue, bloom card.
- Library: all 3 tabs, tab-switch animation, course spotlight + grid, case-study cards → modal (focus trap, Esc), failure cards → modal.
- Shell: sidebar collapse, oracle search, mode switch, dark-mode toggle across all of the above.

Confirm no visual regressions vs. the pre-migration commit (`git stash` comparison or screenshots).

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "refactor: complete file split + Tailwind migration"
```

---

## Self-Review

**Spec coverage:**
- globals.css → tokens + utilities + radar-deck + keyframes: Tasks 3, 31. ✓
- tailwind.config.js with CSS-var token references: Task 2. ✓
- useMode extracted: Task 4. ✓
- workspace data: Task 5. library data + csBars: Task 6. ✓
- icons consolidated: Task 7. ✓
- shared components (TQItem, RadarBriefingPanel, RadarRow, RadarDeckStack): Tasks 8-11. ✓
- 10 workspace components: Tasks 12-20. ✓
- workspace shell: Task 21. ✓
- 10 library components: Tasks 22-29. ✓
- library shell: Task 30. ✓
- AppShell migration: Task 31. ✓
- build + lint verification: Task 32. ✓

**Type/name consistency:** All components use named exports (`export function X`); all imports use named-import syntax `import { X } from '...'`; `@/` alias used throughout; `useMode` is the single hook name everywhere; prep-chip status keys (`ready`/`in-progress`/`cold`) consistent between RadarRow and RadarDeckStack.

**Placeholder scan:** The `/* ...verbatim... */` markers in data/icon tasks (5, 6, 7) are deliberate — those tasks instruct copying exact existing content rather than re-typing large literals, with explicit source line ranges. All component-conversion tasks contain full JSX. The recurring "Fidelity note" instructs the implementer to confirm exact spacing/color values against the OLD CSS — necessary because not every one of ~2000 CSS lines was inlined into this plan; the mapping table + per-task class lists + source line ranges give the implementer everything needed to translate faithfully.

**Scope:** Single subsystem (one Next.js app's styling/structure). Appropriate for one plan.

---

## Risk Notes

- **Visual drift is the main risk.** Tailwind utility translations are approximations until checked against the old CSS. Mitigation: every component task includes a Fidelity note + source line ranges; the old CSS remains in git history (`git show <pre-Task-3-commit>:src/app/globals.css`) for reference during every conversion.
- **Retained custom classes** (radar-deck, app-layout grid, anim-* keyframe wrappers, lib-section-header reveal, lib-fl-readmore-arrow) are intentional — they cover what inline utilities can't express. Keep them minimal.
- **Tasks must run in order.** Tasks 8-11 (shared) precede the components that import them; data/icons/hook (4-7) precede everything; the page shells (21, 30) come last per page; AppShell (31) can run any time after Task 7.
