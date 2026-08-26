# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**CS-platform** — Joveo Customer Success platform. Two independent projects share this repo:

1. **`frontend/`** — a Next.js 14 web app for Joveo's CS team (workspace, learning library, call simulator).
2. **`Brain/`** — a separate Python pipeline that mines Naren's (a senior CSM) call transcripts to build a coaching taxonomy and rubric-based scoring system. See `Brain/CLAUDE.md`.

## Workflow preferences

- Do not invoke the `superpowers:writing-plans` skill itself — the user considers it a waste of time. Writing a plan document is still fine (and often useful) after a design/spec is approved (e.g. via `superpowers:brainstorming`) — just write it directly rather than going through that skill's process.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`harshilbhanushali-rgb/Agentic-Learning`), via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Multi-context: `CONTEXT-MAP.md` at the root points to each context's `CONTEXT.md` (currently `ask-naren/`; `frontend/` and `Brain/` get theirs lazily). See `docs/agents/domain.md`.

## Commands

Run all commands from inside the `frontend/` directory:

```bash
cd frontend
npm run dev    # Start dev server at http://localhost:3000
npm run build  # Production build (also runs full TypeScript type-check)
npm start      # Run production build
npm run lint   # ESLint
```

No test framework is configured. `npm run build` is the type-check gate — there is no separate `tsc` script.

## Stack

- **Next.js 14** App Router, **TypeScript** (`strict: true`)
- **Tailwind CSS** for component styling
- **State:** React hooks + `localStorage` + `CustomEvent` — no Redux/Zustand, no data fetching
- **Icons:** inline SVG components in `frontend/src/components/icons/index.tsx` — no icon library
- All data is hardcoded mock in `frontend/src/data/` — no API routes, database, or auth

## Architecture

### Layout & directory shape

All source lives under `frontend/`. `frontend/src/app/layout.tsx` wraps every route in `<AppShell>` (`frontend/src/components/AppShell.tsx`), which renders the sidebar + topbar and owns the mode/theme/sidebar state. Pages are thin composition shells; the UI lives in per-component files:

- `frontend/src/components/workspace/` — workspace cards (one file per card, veteran + newbie variants)
- `frontend/src/components/library/` — library tabs, cards, and modals
- `frontend/src/components/shared/` — components used across pages (`TQItem`, `RadarBriefingPanel`, `RadarRow`, `RadarDeckStack`)
- `frontend/src/data/workspace.ts`, `frontend/src/data/library.ts` — all mock data, typed against `frontend/src/types.ts`
- `frontend/src/hooks/useMode.ts` — the mode subscription hook
- `frontend/src/types.ts` — the single source of domain types (`EgoTrap`, `RadarMeeting`, `CaseStudy`, `FailureEntry`, `Mode`, etc.); annotate new data and props against these

Routing: `/` redirects to `/workspace`. `/workspace` and `/library` are implemented; `/simulator` is a stub.

### Mode system (Veteran / Newbie)

Two personas toggled in the topbar render **completely different component trees** within the same page:

1. `AppShell` persists the choice to `localStorage['cs-mode']` and dispatches a `cs-mode-change` `CustomEvent`.
2. `useMode()` (in `src/hooks`) reads `localStorage` on mount and subscribes to that event; `workspace/page.tsx` and `library/page.tsx` branch on its return value.
3. `AppShell` keeps its own `mode` state separate from `useMode()` (it both controls and is the source of the event), so the switcher lives there, not behind the hook.

### Dark mode

Toggled in `AppShell`, persisted to `localStorage['cs-theme']`, applied as `[data-theme="dark"]` on `document.documentElement`. `layout.tsx` runs a tiny inline `<script>` before paint to set the attribute from `localStorage` (prevents a flash). Tailwind's `darkMode` is configured as the `[data-theme="dark"]` selector.

### Styling: tokens + Tailwind + residual CSS

The design system is **driven by CSS custom properties**, not by Tailwind's config:

- `frontend/src/app/globals.css` `:root` and `[data-theme="dark"]` define all `--color-*`, `--space-*`, `--radius-*`, `--shadow-*`, motion, and `--sb-*` (sidebar palette) tokens in OKLCH. **To change a color, edit globals.css** — `tailwind.config.js` only *references* these via `var(--…)`, so utilities like `bg-surface` / `text-ink` resolve to the CSS variables and dark mode works automatically.
- **Border-color token is named `line` / `line-subtle`** (e.g. `border-line`), not `border` — this avoids clashing with Tailwind's `border` width utility.
- `globals.css` is **not** purely tokens (~1100 lines). It retains CSS that cannot be expressed as inline utilities, and several components legitimately still use these semantic classes:
  - **Radar deck 3D stacking** — `radar-deck-*`, `rdc-*`, `rdn-*`, `radar-prep*` (used by `RadarDeckStack`).
  - **App shell** — the `app-layout` collapse grid and the full `sidebar-*` / `topbar-*` / `oracle-*` / `mode-*` rules (used by `AppShell`).
  - **Expand/collapse** — the `grid-template-rows: 0fr → 1fr` pattern via the custom utilities `.grid-rows-0fr` / `.grid-rows-1fr` (toggled on ego-trap mirror, radar briefings, newbie track).
  - **Keyframes + `.anim-*` wrappers** (`anim-modal`, `anim-backdrop`, `anim-spotlight`, etc.), plus `.lib-section-header` (reveal) and `.lib-fl-card` (hover watermark + read-more arrow).
- Design north star: **"The Mentor's Desk"** — professional, typography-first, no gamification. Amber **accent** color (`--color-accent`) is used sparingly (≤10% of a screen). All animations respect `prefers-reduced-motion` (global rule in globals.css). Fuller design notes are in `DESIGN.md`.

### Path alias

`@/*` maps to `./src/*` (in `tsconfig.json`). Use `@/components/...`, `@/data/...`, `@/types`.

## Conventions

- Components using hooks/state/effects/refs/event handlers need `'use client'` at the top; pure presentational components (most cards, icons) do not.
- Modals (`CaseStudyModal`, `FailureModal`) use `createPortal` to `document.body` and implement their own focus trap + Escape handling — preserve that when editing.
- Match the existing Tailwind translation style: arbitrary values (`text-[11px]`, `tracking-[0.06em]`) and inline `style={{ … }}` with `var(--…)` are used where a token or utility doesn't fit; CSS custom properties in `style` need an `as CSSProperties` cast under strict TS.

---

## Brain/ — Naren's Brain Pipeline

A separate Python project (own venv, own dependencies) that lives entirely under `Brain/` — unrelated to the Next.js app above. It has its own **`Brain/CLAUDE.md`**, which Claude Code loads automatically whenever you're working inside that directory. Go there for:

- Commands (venv activation, tests, calibration scripts, running the pipeline)
- Stack, architecture, transcript format, embedding API, checkpointing
- Pointers to `Brain/docs/GOTCHAS.md`, `Brain/docs/SCHEMA.md`, and `Brain/docs/findings/INDEX.md` — the full calibration/research history (dozens of measured experiments across Layer A/B/C/D), which used to live inline in this file and has since been split out by topic so it loads on demand instead of by default.

## Ask Naren

A third context sharing this repo: an internal tool where a CSM describes a live client situation and gets one answer grounded in Naren's closest real historical response, or a decline. Its docs, ADRs, glossary and audit harnesses are in `ask-naren/`; its **runtime lives in `Brain/ask_naren/`** because it reuses Brain's storage, gateway and embedder directly. See `CONTEXT-MAP.md`.

```bash
cd Brain
python ops/serve_ask_naren.py --ask "<situation>"   # answer one situation end to end, then exit
python ops/serve_ask_naren.py                        # serve on 127.0.0.1:8787
```

Needs the Joveo VPN. Reads Postgres once at startup and closes the connection before serving — it cannot write to Brain's pipeline.

Do not re-derive or re-propose a threshold, clustering method, or matching strategy for the Brain pipeline without first checking `Brain/docs/findings/INDEX.md` — most ideas here have already been tried and measured, with the outcome recorded.
