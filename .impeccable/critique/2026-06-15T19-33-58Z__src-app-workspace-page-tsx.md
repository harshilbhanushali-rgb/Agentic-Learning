---
target: workspace (and library)
total_score: 24
p0_count: 1
p1_count: 2
timestamp: 2026-06-15T19-33-58Z
slug: src-app-workspace-page-tsx
---
### Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Prep status / progress / "Oracle live" dot present, but no save/loading/sync states — "Calendar sync" is a static label. |
| 2 | Match System / Real World | 4 | Domain language is excellent — QBR, waterfall, "Mirror · Not a score," relative dates. Reads like a CS rep wrote it. |
| 3 | User Control and Freedom | 2 | Modals have Escape/close; but Newbie track "cannot be skipped" and locked steps everywhere — low freedom by design. |
| 4 | Consistency and Standards | 3 | Strong token system; but two divergent radar UIs (deck vs rows) and four different close vocabularies. |
| 5 | Error Prevention | 2 | Locked items use aria-disabled + tooltips; no confirmation on mode switch (wipes the screen instantly). |
| 6 | Recognition Rather Than Recall | 3 | Oracle suggestions + labeled nav, but collapsed sidebar goes to 0px with no icon rail → pure recall. |
| 7 | Flexibility and Efficiency | 3 | ⌘K affordance + shortcut chips shown, but none are wired — decorative. |
| 8 | Aesthetic and Minimalist Design | 3 | Genuinely restrained, typography-first, accent <10%; Ego Trap mirror panel borders on busy. |
| 9 | Error Recovery | 1 | No error states anywhere (mock prototype). |
| 10 | Help and Documentation | 1 | No help/onboarding/tooltips beyond lock hints; no first-run guidance. |
| **Total** | | **24/40** | **Acceptable — solid foundation, weak on system-feedback heuristics (expected for a read-only mock).** |

### Anti-Patterns Verdict

**Does this look AI-generated? Mostly no.** The copy is specific, layouts are asymmetric (1fr + fixed right rail, not 3-up grids everywhere), and there's a real point of view.

**LLM assessment** — three restrained slop tells:
- **Zero-padded numbered step markers** (`Step 01/02/03`) in RadarBriefingPanel.tsx:60 — the single most "AI" signature in the app.
- **Eyebrow kickers everywhere** — tiny uppercase tracked micro-labels are the dominant labeling pattern across nearly every panel header and meta line. Consistent enough to read as a system, but the density is itself a tell.
- **Mild tinted left-border accent** on active waterfall/Bloom rows — acceptable, not a literal side-stripe.
- No gradient text, no glassmorphism, no hero-metric template. The Ego Trap explicitly refuses scoring ("Mirror · Not a score") — the strongest anti-slop signal in the build.

**Deterministic scan**: `detect.mjs` over `src/components` + `src/app` returned **0 findings (exit 0, clean)**. The detector confirms no mechanical slop patterns. Every issue below was caught by design/a11y review, not the scanner — the scanner cannot see keyboard access, contrast ratios, or cognitive load.

**Visual overlays**: not available. Dev server was down and no browser automation exists in this environment, so no user-visible overlay was injected. Findings are from source review only.

### Overall Impression
This is a genuinely thoughtful internal tool with a real soul — the "Mirror, not a score" concept converts a surveillance feature into coaching, and progressive disclosure keeps dense panels survivable. It does NOT read as template AI output. The biggest opportunity: the custom RadarDeckStack (the Veteran's primary content surface) is the least accessible component in the app, and several interactive controls have no visible focus state. Fixing accessibility would move this from "polished prototype" to "shippable tool."

### What's Working
1. **"Mirror, not a score" (Ego Trap)** — a real product insight expressed in UI: no grade, "moments applied / moments missed" cross-referenced to modules, affirmation-first. The soul of the product.
2. **Token-driven design system with discipline** — OKLCH tokens, full dark-mode parity, accent held under 10%, the `line`/`line-subtle` naming to dodge Tailwind's `border` collision. High consistency across ~24 components.
3. **Progressive disclosure as core grammar** — the `0fr→1fr` expand pattern + portal modals keep dense content collapsed until summoned. This is why the density is survivable.

### Priority Issues

**[P0] Keyboard & screen-reader access on RadarDeckStack is broken for all but the front card.**
- Why it matters: A keyboard/SR user can perceive only one of three meetings at a time; paging never announces which meeting moved to front. This is the Veteran's primary content surface.
- Fix: Make each deck card a real focusable region; on navigate, move focus to the new front card and announce its account/title via aria-live; drop the 360ms timeout gate for reduced-motion users.
- Suggested command: /impeccable audit

**[P1] Mode switch silently nukes the entire screen with no orientation, and the toggle has no focus ring.**
- Why it matters: A Veteran who mis-clicks "Newbie" suddenly sees a 90-day mandatory track and may think the app broke. `.mode-btn` has no focus-visible style.
- Fix: Add a brief inline confirmation/toast on switch; add `:focus-visible` outlines to `.mode-btn`, `.topbar-notif-btn`, `.sidebar-toggle-btn`, `.oracle-result`.
- Suggested command: /impeccable audit

**[P1] Collapsed sidebar disappears entirely (0px) — no icon rail, nav becomes pure recall.**
- Why it matters: Collapsing for focus loses all navigation affordance; users must re-expand to switch pages. The `G W/L/S` shortcut chips are decorative (unwired).
- Fix: Collapse to a ~56px icon rail with tooltips, or wire the `G _` shortcuts so collapse is viable.
- Suggested command: /impeccable adapt

**[P2] Decorative ⌘K and shortcut chips imply functionality that doesn't exist.**
- Why it matters: Showing keyboard affordances that don't work erodes power-user trust on first keypress.
- Fix: Wire ⌘K to focus the Oracle input and `G _` chords to route; or remove the chips.
- Suggested command: /impeccable harden

**[P2] Low-contrast meta text carries real information.**
- Why it matters: `--color-ink-placeholder` (oklch ~0.465 light / ~0.478 dark) is used for primary 9–10px uppercase meta labels (status, timing) likely below 4.5:1 — worse in dark mode.
- Fix: Bump meta-text color toward ink, or reserve placeholder-gray for non-essential text only.
- Suggested command: /impeccable audit

### Persona Red Flags

**Alex (power user):** ⌘K and `G W/L/S` are visual lies (no handlers). RadarDeck arrows are the only path to meetings 2–3 and are throttled 360ms. Collapsing the sidebar destroys nav. Mode toggle has no focus ring.

**Sam (accessibility-dependent):** Deck mid/back cards are aria-hidden + pointer-events:none — one meeting in the a11y tree at a time, no announce on page. Missing focus-visible on notif/theme/mode/sidebar/oracle controls; search input has `outline:none`. Low-contrast ink-placeholder meta text below AA, worse in dark mode.

**Jordan (Newbie first-timer):** Tone is stern — "cannot be skipped," "Fixed · mandatory until day 90," stacked locked rows read as compliance, not mentorship. Apply phase is locked with no preview of the payoff. Domain jargon (Bloom's, waterfall, Mirror) unglossed for a day-41 newbie.

### Minor Observations
- Four close vocabularies for one concept (`✕`, "Close ▲", "Hide briefing ▾", "Hide mirror ▾").
- `aria-selected="false"` hard-coded on every Oracle result; no active-descendant, so arrow-key selection isn't wired despite `role="listbox"`.
- EgoTrapCard `text-warning` on `bg-accent-surface` mixes warning + accent semantics.
- NewbieRadarCard hard-codes a "Cohort sync" row outside the data array (data/static drift).
- Simulator stub references `--nav-height` (58px) while the app uses `--topbar-height` (50px) — leftover.

### Questions to Consider
1. The Ego Trap fires every day on recorded calls — has anyone designed the moment a rep opens the app after a call they *know* went badly? That's the highest-emotion moment in the product and it's just an always-open card.
2. Why two completely different radar UIs (3D deck vs flat rows)? The deck is the least accessible component and the rows are clearly more usable — is the 3D stack earning its cost?
3. The Newbie experience is built on locks and mandates — what would it look like framed as a mentor's recommended path the rep chooses, the way the Veteran side does "Mirror, not a score"?
