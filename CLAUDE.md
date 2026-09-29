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
npm run type-check   # tsc --noEmit -- the only check that type-checks TEST files; next build does not
npm test       # vitest: sign-in, sessions, the proxy route -- against real Postgres (PGlite, in-process)
npm run users -- --help   # admin CLI for Ask Naren users (needs ASK_NAREN_ADMIN_DATABASE_URL)
```

`npm test` covers `src/server/` and the API routes only; there are no component tests. `npm run build` is still the type-check gate — there is no separate `tsc` script. **Don't run `next` or `vitest` through the shell hook.** RTK rewrites `next start` into a build summary, and its vitest summary reports `FAIL (0)` even when whole test files fail to load. Use `node node_modules/next/dist/bin/next start` and `node node_modules/vitest/vitest.mjs run`, and read the `Test Files` line.

## Stack

- **Next.js 14** App Router, **TypeScript** (`strict: true`)
- **Tailwind CSS** for component styling
- **State:** React hooks + `localStorage` + `CustomEvent` — no Redux/Zustand. No data fetching library: the one page that fetches (`/ask-naren`) uses bare `fetch` against a same-origin route
- **Icons:** inline SVG components in `frontend/src/components/icons/index.tsx` — no icon library
- All page data is hardcoded mock in `frontend/src/data/`. **One API route exists**: `frontend/src/app/api/ask-naren/route.ts`, a pass-through proxy to the Python Ask Naren service that holds no retrieval, grounding or model logic — see `ask-naren/` and `Brain/CLAUDE.md`
- **Sign-in (Ask Naren only)** — hand-rolled sessions, ADR 0011. `frontend/src/server/` is server-only code: `db.ts` (the `Db` seam over `pg`; `ASK_NAREN_DATABASE_URL`), `auth/` (scrypt passwords, session rows keyed on the token's SHA-256, users, the admin CLI's logic). Tables are in the `ask_naren` Postgres schema of Brain's Neon instance, from `frontend/db/migrations/`, applied by hand — never by the app. **The app connects as SQL-created roles, never Console-made ones** (ADR 0012: Console roles join `neon_superuser` and can write `kb_pairs`). `ask_naren_app` is the web app and `ask_naren_admin` is the CLI; grants are in `frontend/db/provision/grants.sql`, which must be re-run after every new migration. Setup is in `frontend/db/provision/README.md`. On first use the app refuses to serve a role that could reach Brain's tables (`src/server/privilege.ts`). **Who is signed in is asked in one place**: `getCurrentUser` / `requireUser` in `auth/current-user.ts` for pages and actions, `validateSession` directly in the proxy route — never in `middleware` or a layout (issue #42). No session is `null`; a database fault throws, and must never be turned into "signed out"

## Architecture

### Layout & directory shape

**Ask Naren is the only live page (since 2026-09-28).** Workspace, Library and Simulator are **archived**, not deleted. Their routes are in `frontend/src/app/_archive/`, a private folder, so Next serves no route for them, but they are still type-checked by the build. The full app shell that went with them is in `frontend/src/components/_archive/AppShell.tsx`: the Oracle search, the Veteran/Newbie switch, notifications, and the mock "Today" items and profile. To restore a page, move its folder back out of `_archive/` and restore that shell. The workspace/library components, data, `useMode` and the mode CSS below are kept for that.

All source lives under `frontend/`. `frontend/src/app/layout.tsx` wraps every route in `<AppShell>` (`frontend/src/components/AppShell.tsx`). While Ask Naren is the only page, that shell is just the sidebar (one item), the collapse toggle and the theme toggle. Pages are thin composition shells; the UI lives in per-component files:

- `frontend/src/components/workspace/` — workspace cards (one file per card, veteran + newbie variants)
- `frontend/src/components/library/` — library tabs, cards, and modals
- `frontend/src/components/shared/` — components used across pages (`TQItem`, `RadarBriefingPanel`, `RadarRow`, `RadarDeckStack`)
- `frontend/src/components/ask-naren/` — the Ask Naren page's three components (`SituationForm`, `AnswerCard`, `DeclineNotice`). Unlike workspace/ and library/ these have **no veteran/newbie variants**, deliberately: the page must render identically in both modes, and not branching is the only implementation of that which cannot drift
- `frontend/src/data/workspace.ts`, `frontend/src/data/library.ts` — all mock data, typed against `frontend/src/types.ts`
- `frontend/src/hooks/useMode.ts` — the mode subscription hook
- `frontend/src/types.ts` — the single source of domain types (`EgoTrap`, `RadarMeeting`, `CaseStudy`, `FailureEntry`, `Mode`, etc.); annotate new data and props against these. `AskNaren*` at the bottom mirror the Python service's response contract **exactly** and must not drift from it — `AskNarenResponse` is a discriminated union on `outcome` (`answered` | `declined` | `clarify`), which is what makes the render paths exhaustive. Note the service ALSO has a `declined` key inside the model's own JSON — that one is the frozen prompt contract from ADR 0001 and is a different thing entirely

Routing: `/` redirects to `/ask-naren`. Live routes are `/ask-naren`, `/login` and `/api/ask-naren/**`; the archived pages return 404. `/ask-naren` is the only page that talks to a backend, the only one that requires sign-in (`/login`), and the only one that is mode-agnostic. `ask-naren/page.tsx` is a server wrapper that resolves the user; the page body is `components/ask-naren/AskNaren.tsx`.

### Mode system (Veteran / Newbie), archived

**Not live:** the switch was in the archived shell, and Ask Naren renders identically in both modes. It is described here for restoring the archived pages. Two personas toggled in the topbar render **completely different component trees** within the same page:

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

**It answers about six CSMs at once, and that ceiling is not ours to raise.** The limit is the gateway's 8 requests in flight per API *key* — shared across chat and embeddings — operated at 6 so a retry has somewhere to go. Behind those six, `Brain/ask_naren/admission.py` queues as many as the 30s request deadline can absorb and refuses anyone past that immediately with an estimate (a `service_busy` decline, HTTP 429) rather than accepting them and failing later. Thirteen of the nineteen intents are *rendered* and never reach the generation budget at all, so in normal use the queue is empty or one deep; at the other extreme, thirty simultaneous generating questions means the people past the queue are turned away rather than left on a spinner.

**Do not run a second process to get more capacity.** The gateway's budget belongs to the key, and each process keeps its own limiter — N processes violate one budget by construction, with no way to coordinate, while every health check passes. More capacity means more key allowance or sharding across keys. Same reason there is exactly one `asyncio.run` in `ops/serve_ask_naren.py`: the transport's admission gate is keyed on the running loop, and a loop per request silently makes the per-key bound unbounded. Full reasoning in `ask-naren/docs/adr/0010-ask-naren-answers-concurrently-in-one-asyncio-process.md`, which supersedes ADR 0003.

**No latency figure is quoted HERE on purpose** — an answer's cost has moved by several times between runs, so a number written into this file is stale within a day and checkable against nothing. Where a capacity figure is unavoidable (the ADR states throughput, because a reader needs one) it is labelled a planning figure rather than a measurement. The harnesses in `ask-naren/audit/` do the measuring and write to that directory's `artifacts/`.

**Vector search runs in Pinecone** (index `narens-brain-3072`), not in the service process — ADR 0008. The startup Postgres read supplies the pool's TEXT, which stays there deliberately: Pinecone's metadata is truncated to 500 characters by the pipeline's upsert, and the grounding gate needs the full response to verify a quote verbatim. Ask Naren issues no writes anywhere — no upsert, no index creation. After any Layer B ship, run `Brain/ops/check_vector_coverage.py`.

Do not re-derive or re-propose a threshold, clustering method, or matching strategy for the Brain pipeline without first checking `Brain/docs/findings/INDEX.md` — most ideas here have already been tried and measured, with the outcome recorded.

**Before scoping any new Ask Naren intent, answer path or eval set, read `ask-naren/docs/findings/`.** Two findings there set expectations that are easy to get wrong and expensive to discover late:

- `corpus-is-onboarding-not-escalation.md` — Naren's recorded calls are dominated by getting clients live, not by rescuing running campaigns. Exactly one of the twelve most-supported situations is about ongoing performance. So a feature measured on onboarding questions will look accurate and then decline or misroute on the escalation questions it was built for. Check coverage before scoping, and draw eval questions from the covered situations rather than from intuition about CS work.
- `answer-failure-modes.md` — when it is wrong, the retrieved exchange is on the right topic and answers a different question. Confidently worded, correctly sourced, wrong. Issue #9.
