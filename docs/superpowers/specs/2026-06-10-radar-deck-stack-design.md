# Radar Deck Stack — Design Spec

**Date:** 2026-06-10  
**Surface:** `src/app/workspace/page.js` + `src/app/globals.css`  
**Status:** Approved, ready for implementation

---

## Overview

Replace the current flat `RadarRow` list in `WeeklyRadarCard` with a stacked card deck (`RadarDeckStack`) that supports N meetings. The deck shows 3 cards at a time (front, mid, back) using CSS transform offsets. The front card expands in-place to reveal the full meeting briefing. Navigation arrows cycle through all meetings.

This replaces the existing `RadarBriefingPanel` expand-below-row pattern for the veteran workspace radar. The newbie radar (`NewbieRadarCard`) is unaffected.

---

## Components

### `RadarDeckStack`

**Props:** `meetings` (array, all RADAR_MEETINGS data)

**State:**
- `activeIndex` — integer, 0-based, clamped to `[0, meetings.length - 1]`
- `open` — boolean, whether the front card's briefing is expanded

**Rendered slots:**
- Back card: `meetings[activeIndex + 2]` (or ghost card if out of bounds)
- Mid card: `meetings[activeIndex + 1]` (or ghost card if out of bounds)
- Front card: `meetings[activeIndex]`

A ghost card is a placeholder with no content that fills the stack depth visually when fewer than 3 meetings remain at the tail.

---

### `RadarDeckCard`

**Props:** `meeting`, `slot` (`'front' | 'mid' | 'back'`), `open` (boolean, front only), `onToggle` (front only)

**Structure:**

```
.radar-deck-card  [data-slot="front|mid|back"]  [class="is-open" when expanded]
  .rdc-header
    .rdc-time-row        ← day · time · relative chip
    .rdc-prep-badge      ← prep status pill
  .rdc-title-row         ← account name — meeting title
  .rdc-meta-row          ← industry · tags
  .rdc-expand            ← grid-template-rows expand zone (front card only)
    .rdc-expand-inner
      RadarBriefingPanel ← existing component, reused unchanged
      .rdc-expand-footer ← [ Close ↑ ] button
```

Mid and back cards render only `.rdc-header`, `.rdc-title-row`, `.rdc-meta-row` — no expand zone.

---

### `RadarDeckNav`

**Props:** `activeIndex`, `total`, `onPrev`, `onNext`, `open` (to disable nav during open state or handle close-then-navigate)

Renders: `‹  2 / 5  ›`

---

## Layout

```
.radar-deck-section           ← replaces current .et-card radar section wrapper
  .radar-deck                 ← position: relative; height driven by front card
    .radar-deck-card[back]    ← position: absolute, full width, behind
    .radar-deck-card[mid]     ← position: absolute, full width, behind
    .radar-deck-card[front]   ← position: relative (drives height), in front
  .radar-deck-nav             ← below stack, always visible
```

All cards are `width: 100%` of `.radar-deck`. The stacked illusion is pure CSS transforms — no fixed pixel widths.

---

## CSS Transforms by Slot

| Slot | transform | opacity | filter |
|------|-----------|---------|--------|
| back | `translateY(-14px) translateX(6px) scale(0.93)` | `0.45` | `grayscale(60%)` |
| mid | `translateY(-7px) translateX(3px) scale(0.96)` | `0.65` | `grayscale(25%)` |
| front (closed) | `translateY(0) translateX(0) scale(1) skewY(-8deg)` | `1` | none |
| front (open) | `translateY(0) translateX(0) scale(1) skewY(0deg)` | `1` | none |
| back (when front open) | `translateY(-20px) translateX(8px) scale(0.91)` | `0.2` | `grayscale(80%)` |
| mid (when front open) | `translateY(-10px) translateX(4px) scale(0.94)` | `0.3` | `grayscale(50%)` |

Right-edge gradient fade: `::after` pseudo-element on each card, `position: absolute`, `right: 0`, `top: 0`, `height: 110%`, `width: 30%`, `background: linear-gradient(to left, var(--color-bg), transparent)`. Pointer-events: none.

---

## Animation Spec

| Event | Properties animated | Duration | Curve | Notes |
|-------|-------------------|----------|-------|-------|
| Card open | `transform` (skewY), `grid-template-rows` | 350ms | `ease-out-expo` | Both fire simultaneously |
| Back/mid recede on open | `transform`, `opacity`, `filter` | 200ms | `ease-out-quart` | |
| Card close | reverse of open | 260ms | `ease-out-quart` | Slightly faster than open |
| Nav switch | `opacity` on outgoing front card | 150ms | `ease-out-quart` | Close briefing first if open, then switch |
| Nav switch (incoming) | `opacity` fade in | 200ms | `ease-out-quint` | Starts after outgoing finishes |
| Arrow button hover | `translateX(±2px)` | 100ms | `ease-out-quart` | |

**Easing tokens** (already in globals.css — use existing `--ease-out-expo`, `--ease-out-quart`):
```css
--ease-out-expo:  cubic-bezier(0.16, 1, 0.3, 1);
--ease-out-quart: cubic-bezier(0.25, 1, 0.5, 1);
--ease-out-quint: cubic-bezier(0.22, 1, 0.36, 1);
```

**Nav close-then-switch sequence (JS):**
```js
// If open, close first, then switch after 260ms
if (open) {
  setOpen(false);
  setTimeout(() => setActiveIndex(newIndex), 260);
} else {
  setActiveIndex(newIndex);
}
```

**`prefers-reduced-motion`:** All transitions set to `0.01ms`. Content still reveals; no motion.

---

## Content: Briefing Inside the Card

`RadarBriefingPanel` is reused without modification. It already renders:
- Expert clip card (play btn + quote + waveform)
- AI tip card
- Waterfall steps (done/active/locked)
- Footer with "Mark prepped" CTA

The `.rdc-expand-footer` below it adds a `[ Close ↑ ]` text button to collapse.

---

## Data

`RADAR_MEETINGS` array in `workspace/page.js` is unchanged. `RadarDeckStack` receives the full array. Ghost cards are rendered via index-bounds checking in the component:

```js
const backMeeting  = meetings[activeIndex + 2] ?? null;
const midMeeting   = meetings[activeIndex + 1] ?? null;
const frontMeeting = meetings[activeIndex];
```

Ghost card renders as `.radar-deck-card[data-slot="back"]` or `"mid"` with no inner content and `aria-hidden="true"`.

---

## Accessibility

- Front card: `role="button"`, `aria-expanded={open}`, `tabIndex={0}`, keyboard `Enter`/`Space` toggles
- Nav arrows: `aria-label="Previous meeting"` / `"Next meeting"`, `disabled` at bounds — linear navigation, not circular. Prev disabled at index 0, Next disabled at `meetings.length - 1`.
- Back/mid cards: `aria-hidden="true"`, `tabIndex={-1}`, `pointer-events: none`
- Counter: `aria-live="polite"` so screen readers announce index change

---

## Files Modified

| File | Change |
|------|--------|
| `src/app/workspace/page.js` | Add `RadarDeckStack`, `RadarDeckCard`, `RadarDeckNav` components. Remove `RadarRow` usage from `WeeklyRadarCard`. Keep `RadarBriefingPanel` unchanged. |
| `src/app/globals.css` | Add `.radar-deck-section`, `.radar-deck`, `.radar-deck-card`, `.rdc-*` tokens, `.radar-deck-nav` styles. Add animation transitions. Add `prefers-reduced-motion` block. |

---

## Out of Scope

- Newbie radar (`NewbieRadarCard`) — unchanged
- Ego Trap history stack — separate future feature
- Library / Simulator pages — untouched
