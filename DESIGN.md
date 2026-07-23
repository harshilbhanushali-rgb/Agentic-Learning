---
name: Joveo CS Platform
description: AI-powered knowledge and learning platform for Customer Champions
colors:
  primary: "oklch(0.428 0.198 256)"
  primary-hover: "oklch(0.372 0.208 256)"
  primary-active: "oklch(0.322 0.215 256)"
  primary-surface: "oklch(0.948 0.034 256)"
  primary-subtle: "oklch(0.968 0.020 256)"
  accent: "oklch(0.858 0.092 80)"
  accent-on: "oklch(0.210 0.055 75)"
  accent-ink: "oklch(0.320 0.085 75)"
  accent-surface: "oklch(0.965 0.028 80)"
  bg: "oklch(1.000 0.000 0)"
  surface: "oklch(0.967 0.006 256)"
  surface-raised: "oklch(0.942 0.008 256)"
  line: "oklch(0.882 0.009 256)"
  line-subtle: "oklch(0.928 0.006 256)"
  ink: "oklch(0.135 0.014 256)"
  ink-2: "oklch(0.420 0.010 256)"
  ink-placeholder: "oklch(0.465 0.010 256)"
  success: "oklch(0.415 0.140 150)"
  success-surface: "oklch(0.960 0.038 150)"
  warning: "oklch(0.415 0.128 68)"
  warning-surface: "oklch(0.964 0.028 68)"
  error: "oklch(0.475 0.190 25)"
  error-surface: "oklch(0.960 0.038 25)"
typography:
  display:
    fontFamily: "Geist Sans, Inter, system-ui, sans-serif"
    fontSize: "clamp(1.5rem, 3vw, 2rem)"
    fontWeight: 800
    lineHeight: 1.35
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Geist Sans, Inter, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.35
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Geist Sans, Inter, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "normal"
  body:
    fontFamily: "Geist Sans, Inter, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  label:
    fontFamily: "Geist Mono, ui-monospace, SF Mono, Menlo, monospace"
    fontSize: "0.625rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.06em"
rounded:
  sm: "4px"
  md: "8px"
  lg: "12px"
  xl: "20px"
  full: "9999px"
spacing:
  1: "0.25rem"
  2: "0.5rem"
  3: "0.75rem"
  4: "1rem"
  5: "1.25rem"
  6: "1.5rem"
  8: "2rem"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.bg}"
    rounded: "{rounded.sm}"
    padding: "0 1.25rem"
    height: "38px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.bg}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sm}"
    padding: "0 0.75rem"
    height: "28px"
  chip:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.full}"
    padding: "3px 0.5rem"
  card:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "1.25rem"
  tq-take:
    backgroundColor: "transparent"
    textColor: "{colors.primary}"
    rounded: "{rounded.sm}"
    padding: "0 0.5rem"
    height: "24px"
---

# Design System: Joveo CS Platform

## 1. Overview

**Creative North Star: "The Mentor's Desk"**

A professional workspace built around one idea: the best colleague always has the right context ready, never makes you feel judged for not knowing something, and gets you to the answer fast. The visual system carries that feeling materially — clear enough to scan under pressure, warm enough to feel safe when learning, quiet enough that the content is always the protagonist.

The system uses **tonal restraint** as its primary language: space, weight, and subtle warmth do the work other platforms hand to color. Two saturated colors exist, and they earn their appearances. A **cobalt/indigo primary** carries interactive UI — CTAs, active states, AI-surfaced insight markers, live indicators. An **amber-gold accent** is rarer still, reserved for signal moments (a knowledge drop, a Bloom's badge, a "recommended for you" mark). Everything else lives in tonal variants of a single near-neutral family.

This system explicitly rejects: the neutral-gray minimal-everything of generic SaaS (Notion, Linear); the widget-dense corporate LMS (Workday, SAP); the gamification and bright primaries of consumer edtech (Duolingo, Coursera); and the cramped dashboard syndrome of CRMs (Salesforce, HubSpot). None of those feel like a mentor. This one must.

**Key Characteristics:**
- Tonal and spatial, not chromatic and busy
- Near-white canvas; a cobalt primary for action and an amber accent for rare signal
- Typography-led hierarchy — weight and size carry the structure; OKLCH throughout
- Responsive motion only: state feedback and grid-row expand/collapse, never choreography for its own sake
- Content-forward: the UI recedes; what the Champion needs advances
- Light and dark themes both meet AA independently, driven by `[data-theme="dark"]`

## 2. Colors

A near-neutral cobalt-tinted family carries surfaces and text; one cobalt primary and one amber accent carry meaning. All values are OKLCH and live in `src/app/globals.css` as CSS custom properties — `tailwind.config.js` only references them, so dark mode reassigns the same token names.

### Primary
- **Cobalt** (`oklch(0.428 0.198 256)`): The interactive color. Primary CTAs, active nav, AI insight markers (Ego Trap dot, AI-tip icon), `Now` step badges, the test-queue radio and "Take" action. Hover deepens to `oklch(0.372 0.208 256)`, active to `oklch(0.322 0.215 256)`. `primary-surface` / `primary-subtle` are its tinted backgrounds for AI-tip cards, active waterfall steps, and the Bloom active row.

### Secondary
- **Amber-Gold Accent** (`oklch(0.858 0.092 80)`): The scarcity color. Library tab underline, the "Recommended for you" spotlight badge, the Newbie Bloom badge. Text-on-amber is `accent-on` (`oklch(0.210 0.055 75)`); `accent-surface` is its faint wash (used as the "what you missed" mirror tint).

### Tertiary (status)
- **Success** (`oklch(0.415 0.140 150)`) / **Warning** (`oklch(0.415 0.128 68)`) / **Error** (`oklch(0.475 0.190 25)`), each with a `-surface` wash. Carry prep status (Prepped / In-Progress / Cold radar chips), applied-vs-missed mirror columns, and completion state. Status is **never** the sole signal — paired with icon + label.

### Neutral
- **Background** (`oklch(1.000 0.000 0)`): The canvas — true white at chroma 0. The content zone sits on `surface`.
- **Surface** (`oklch(0.967 0.006 256)`) / **Surface-raised** (`oklch(0.942 0.008 256)`): Tonal layering for panels, hovers, and pills — depth without shadow.
- **Line / Line-subtle** (`oklch(0.882 0.009 256)` / `oklch(0.928 0.006 256)`): Dividers and card borders. **Token is `line`, not `border`** — written `border-line` in markup, deliberately renamed to avoid clashing with Tailwind's `border` width utility.
- **Ink** (`oklch(0.135 0.014 256)`): Body and heading text — near-black, cobalt-tinted, AA with room to spare.
- **Ink-2** (`oklch(0.420 0.010 256)`): Supporting text, metadata. A genuine mid-dark, AA-compliant.
- **Ink-placeholder** (`oklch(0.465 0.010 256)`): Placeholder, timestamps, locked-state labels — still AA.

### Sidebar palette
The sidebar runs its own `--sb-*` ramp (sunken, distinctly darker than the content canvas in both themes) so it reads as a separate plane. Both light and dark variants are defined; the dark block is placed after the light `:root` so it wins by source order.

### Named Rules
**The Two-Signal Rule.** Cobalt is for *action and interactivity*; amber is for *rare signal*. Cobalt may appear on any screen; amber stays ≤10% and marks moments, not chrome. They are never interchangeable and never decorative.

**The Consistent Accent Rule.** Both saturated colors keep their hue across light and dark mode — lightness shifts for contrast, hue does not. A dark mode that swaps the accent hue is a different brand, not a theme.

## 3. Typography

**Display / Body Font:** Geist Sans (with Inter, system-ui fallback)
**Label / Mono Font:** Geist Mono (with ui-monospace, SF Mono, Menlo fallback)

**Character:** One humanist-geometric sans in 4–5 weights carries all reading and heading text; the monospace appears only for small structural labels (eyebrows, radar day codes, sidebar version/meta, case-study metadata) where it signals "system data." Approachable, legible at small sizes, never playful.

### Hierarchy
- **Display** (extrabold 800, `clamp(1.5rem, 3vw, 2rem)`, line-height 1.35, tracking -0.025em): Page greetings ("Good morning, Priya…"). `text-wrap: balance`, capped ~640px.
- **Headline** (bold 700, `1.25rem`/`1.5rem`, line-height 1.35, tracking -0.02em): Card heroes — the Ego Trap question, library page title, case-study/failure headlines.
- **Title** (semibold 600, `0.875rem`–`1rem`, line-height 1.35): Card and panel headings — module names, radar titles, right-panel section titles.
- **Body** (regular 400, `0.875rem`, line-height 1.55): Reading-length content — Ego Trap stats, module descriptions, case-study prose, AI tips. `text-wrap: pretty`; cap 65–75ch.
- **Label** (Geist Mono, semibold 600, `0.625rem`–`0.6875rem`, tracking 0.04–0.08em, uppercase): Eyebrows, status chips, timestamps, sidebar meta, radar day codes, Bloom notes.

### Named Rules
**The Weight-First Rule.** Emphasis is expressed in weight before color. Bold/semibold before any tint. Color on type is reserved for links, interactive labels, and the cobalt/amber signals — never for decorative emphasis of static content.

## 4. Elevation

Flat by default. Surfaces are distinguished by **tonal difference** (bg → surface → surface-raised) and 1–1.5px `line` borders, not by shadow. Cards carry a hairline border at rest; the radar deck's front card is the one place a soft resting shadow appears, to read as a stacked physical card.

### Shadow Vocabulary
- **`--shadow-low`** (`0 1px 3px oklch(0% 0 0 / .05), 0 2px 12px oklch(0% 0 0 / .03)`): Cards/panels at rest or on hover — interactivity, not permanent elevation.
- **`--shadow-ambient`** (`0 4px 20px oklch(0% 0 0 / .08), 0 1px 4px oklch(0% 0 0 / .04)`): Modals, dialogs, hovered library cards — lifted off the page.
- **`--shadow-lifted`** (`0 8px 32px oklch(0% 0 0 / .12), 0 2px 8px oklch(0% 0 0 / .06)`): Reserved for the highest layer.
- **Focus ring:** not a shadow — a 2px solid `primary` outline, `outline-offset: 2px`.

Dark mode raises all shadow alphas (×~4) since shadows must read against a near-black canvas.

### Named Rules
**The Flat-By-Default Rule.** A surface carries no shadow at rest (the radar front card excepted). Low appears on hover, ambient lifts modals/dropdowns, nothing above that. If a surface needs depth to be understood at rest, the layout is wrong.

## 5. Components

### Buttons
- **Shape:** small radius (`4px`, `rounded-sm`).
- **Primary:** `bg-primary` cobalt, white text, height 38px (`btn`) or 28px (`btn--sm`); inline CTAs use a 28px pill (`h-7 px-3`). Hover → `primary-hover` with a 1px lift and soft cobalt glow.
- **Ghost:** transparent with a `line` border, `ink-2` text; hover fills `surface` and darkens to `ink`. The "+ New scratch note" and card toggle actions.
- **Text / inline CTA buttons** ("View mirror", "Open briefing"): borderless, cobalt or ink-2, with a chevron icon that swaps direction on open.

### Chips
- **Tag chip** (`chip--not-started`): `surface-raised` fill, `ink-2` text, 1px `line` border, full radius — course tags, modal category labels.
- **Status chip** (radar prep / weekly radar): 10px mono uppercase, `{status}-surface` fill + `{status}` text (Prepped=success, In-Progress=warning, Cold=error). Pill or small radius.
- **Badge:** `primary-surface`/`primary` for "N new" drops; `accent-surface`/`accent-on` for the Bloom "Newbie" badge.

### Cards / Containers
- **Corner Style:** `8px` (`rounded-md`) for content cards; `12px` (`rounded-lg`) for the spotlight and modals.
- **Background:** `bg`; headers/footers often sit on `surface`.
- **Border:** 1.5px `line` at rest (`border-[1.5px] border-line`). Tonal/hairline, not drawn-heavy.
- **Shadow Strategy:** flat at rest, `--shadow-low` on hover (library/case cards lift `translateY(-2px/-3px)`); see Elevation.
- **Internal Padding:** `1rem`–`1.25rem` (`p-4`/`p-5`).

### Inputs / Fields
- **Knowledge Oracle search:** 34px tall, `surface` fill, 1.5px `line` border, `rounded-sm`. Focus-within shifts the border to `primary` with a 3px cobalt ring and switches fill to `bg`. Houses a live "Oracle live" pulsing success dot and a ⌘K kbd hint.

### Navigation
- **Sidebar items:** `sb-ink-2` text, hover `sb-hover-bg`; active item gets `sb-active-bg`, a cobalt left accent bar (`::before`), and a glowing cobalt dot. Mono shortcut pills (`G W`) recolor cobalt when active.
- **Library tabs:** text tabs with a 2px bottom border; active tab is `ink` with an **amber** (`accent`) underline and semibold weight. Sticky under the topbar.

### Signature Components
- **Radar Deck Stack:** a 3D stack of meeting cards (`data-slot` back/mid/front) with depth via absolute positioning + opacity; the front card expands a Mission Briefing via a `grid-template-rows: 0fr → 1fr` transition. Prev/next deck nav with a tabular counter.
- **Ego Trap card:** live cobalt dot, a horizontally-scrolling meeting pill strip, and a "mirror" that expands into success-tinted (applied) vs amber-tinted (missed) moment columns. Frames coaching as reflection, never a score.
- **Expand/collapse pattern:** every disclosure (mirror, radar briefing, newbie track) animates `grid-template-rows 0fr→1fr` over `--dur-slow` with `--ease-out-expo`; the inner wrapper is `overflow-hidden`.

## 6. Do's and Don'ts

### Do:
- **Do** use weight for hierarchy before color. Cobalt marks action/interactivity; amber marks rare signal. Keep amber ≤10% of any screen.
- **Do** write supporting text at true mid-dark (`ink-2`, `oklch(0.420 …)` or darker) and verify AA (4.5:1) — including placeholders. "Muted gray for elegance" is the top reason AI UIs fail legibility.
- **Do** edit colors in `globals.css` (the CSS variables are the source of truth); `tailwind.config.js` only references them via `var(--…)`.
- **Do** write borders as `border-line` / `border-line-subtle` (the token is `line`, not `border`).
- **Do** use `text-wrap: balance` on h1–h3 and `text-wrap: pretty` on prose; cap reading content at 65–75ch.
- **Do** give every animation a `prefers-reduced-motion` path — there's a global reduce rule in `globals.css`; this platform runs during live client calls.
- **Do** distinguish layers tonally (bg → surface → surface-raised) before adding borders; keep surfaces flat at rest.
- **Do** keep status meaning carried by icon + label, never color alone (Bloom level, prep status, completion).
- **Do** use the semantic z-index scale (`dropdown → sticky → modal-backdrop → modal → toast → tooltip`) — no `999`/`9999`.

### Don't:
- **Don't** make this look like generic SaaS (Notion, Linear) — neutral-gray minimal everything, whitespace-as-personality. This system is warmer, more purposeful, more content-dense.
- **Don't** make this a corporate LMS (Workday, SAP) — no blue gradients, table-dense grids, clipart icons, or "click Next to continue."
- **Don't** make this consumer edtech (Duolingo, Coursera) — no streak badges as chrome, confetti palettes, mascots, or copy that talks down to professionals.
- **Don't** make the Workspace a CRM dashboard (Salesforce, HubSpot) — it's a focused view of right-now, not a wall of KPI widgets.
- **Don't** use a `border-left`/`border-right` stripe wider than 1px as a card or callout accent. Use a background tint, a leading icon, or a numbered marker.
- **Don't** use gradient text (`background-clip: text`). Emphasis via weight or size.
- **Don't** use the warm-neutral band `oklch(L 84–97%, C < 0.06, hue 40–100)` as the body background — that's the cream/sand AI default. Warmth lives in the amber accent, not the canvas (which is true white).
- **Don't** use numbered section eyebrows (01/02/03) or a tiny uppercase tracked kicker above every heading as default scaffolding. The mono label style is for genuine system data (timestamps, day codes), not decorative kickers.
- **Don't** give every section the same entrance animation — motion fits what it reveals (the radar deck reads as physical cards; the mirror is a considered reflection).
