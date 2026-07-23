# Radar Deck Stack — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat `RadarRow` list in `WeeklyRadarCard` with a stacked card deck that supports N meetings, where clicking the front card expands the full briefing in-place with smooth animations.

**Architecture:** `RadarDeckStack` holds `activeIndex` + `open` state and renders three `RadarDeckCard` slots (front/mid/back). Back and mid cards are `position: absolute` and peek above the front card via negative `translateY`. The front card de-skews and its inner `grid-template-rows: 0fr → 1fr` expand zone reveals `RadarBriefingPanel`. Nav arrows cycle through all meetings sequentially.

**Tech Stack:** Next.js 14 App Router, plain CSS with OKLCH tokens, no external animation library (CSS transitions only).

---

## File Structure

| File | What changes |
|------|-------------|
| `src/app/workspace/page.js` | Add `ChevronLeftIcon`, `ChevronUpIcon` icons; add `RadarDeckNav`, `RadarDeckCard`, `RadarDeckStack` components; update `WeeklyRadarCard` to render `RadarDeckStack` instead of the `RadarRow` list. `RadarRow` and `RadarBriefingPanel` stay — `RadarRow` is still used by `NewbieRadarCard`. |
| `src/app/globals.css` | Add `--ease-out-quint` token; add `.radar-deck-wrap`, `.radar-deck-card`, `.rdc-*`, `.radar-deck-nav`, `.rdn-*` CSS; add `prefers-reduced-motion` override block for deck. |

---

## Task 1 — Add `--ease-out-quint` token to globals.css

**File:** `src/app/globals.css`

The nav "incoming card" transition uses `ease-out-quint`, which doesn't exist in globals.css yet. Add it next to the existing easing tokens.

- [ ] **Step 1: Locate the easing token block**

  Find this block (around line 86):
  ```css
    --ease-out-quart: cubic-bezier(0.25, 1, 0.5, 1);
    --ease-out-expo:  cubic-bezier(0.16, 1, 0.3, 1);
  ```

- [ ] **Step 2: Add `--ease-out-quint` on the line after `--ease-out-expo`**

  Change:
  ```css
    --ease-out-quart: cubic-bezier(0.25, 1, 0.5, 1);
    --ease-out-expo:  cubic-bezier(0.16, 1, 0.3, 1);
  ```

  To:
  ```css
    --ease-out-quart: cubic-bezier(0.25, 1, 0.5, 1);
    --ease-out-quint: cubic-bezier(0.22, 1, 0.36, 1);
    --ease-out-expo:  cubic-bezier(0.16, 1, 0.3, 1);
  ```

- [ ] **Step 3: Verify build still passes**

  ```bash
  cd c:/PF/Joveo/CS-platform && npm run build
  ```
  Expected: `✓ Compiled successfully` with no errors.

- [ ] **Step 4: Commit**

  ```bash
  git add src/app/globals.css
  git commit -m "feat: add --ease-out-quint easing token"
  ```

---

## Task 2 — Add deck layout and card slot CSS to globals.css

**File:** `src/app/globals.css`

Add a new `/* ── RADAR DECK STACK ──────────── */` section at the end of the file (before the `@media (prefers-reduced-motion)` block if one exists, otherwise at the very end).

- [ ] **Step 1: Append the deck container and card slot CSS**

  Append to `src/app/globals.css`:

  ```css
  /* ── RADAR DECK STACK ─────────────────────────────────────────── */

  .radar-deck-wrap {
    position: relative;
    padding: 20px var(--space-5) var(--space-4);
    /* padding-top reserves room for back/mid cards that peek above front */
  }

  /* ─ All deck cards share base styles ─ */

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

  /* Right-edge gradient fade — fades content into bg on the right */
  .radar-deck-card::after {
    content: '';
    position: absolute;
    right: 0;
    top: -5%;
    width: 22%;
    height: 110%;
    background: linear-gradient(to left, var(--color-bg), transparent);
    pointer-events: none;
  }

  /* ─ Back card: absolute, peeks above the front card ─ */

  .radar-deck-card[data-slot="back"] {
    position: absolute;
    top: 20px; /* same y-origin as front card */
    left: var(--space-5);
    right: var(--space-5);
    width: auto;
    transform: translateY(-14px) translateX(6px) scale(0.93);
    opacity: 0.45;
    filter: grayscale(60%);
    z-index: 1;
    pointer-events: none;
  }

  /* ─ Mid card: absolute, peeks above the front card less than back ─ */

  .radar-deck-card[data-slot="mid"] {
    position: absolute;
    top: 20px;
    left: var(--space-5);
    right: var(--space-5);
    width: auto;
    transform: translateY(-7px) translateX(3px) scale(0.96);
    opacity: 0.65;
    filter: grayscale(25%);
    z-index: 2;
    pointer-events: none;
  }

  /* ─ Front card: relative (drives container height), skewed when closed ─ */

  .radar-deck-card[data-slot="front"] {
    transform: skewY(-8deg);
    opacity: 1;
    filter: none;
    z-index: 3;
    transition:
      transform 350ms var(--ease-out-expo),
      opacity   200ms var(--ease-out-quart),
      filter    200ms var(--ease-out-quart),
      box-shadow 200ms var(--ease-out-quart);
  }

  .radar-deck-card[data-slot="front"]:not(.is-open):hover {
    box-shadow: 0 4px 16px oklch(0 0 0 / 0.07);
  }

  /* Front card open: de-skew */
  .radar-deck-card[data-slot="front"].is-open {
    transform: skewY(0deg);
  }

  /* ─ Back/mid recede when deck is open ─ */

  .deck-is-open .radar-deck-card[data-slot="back"] {
    transform: translateY(-20px) translateX(8px) scale(0.91);
    opacity: 0.2;
    filter: grayscale(80%);
  }

  .deck-is-open .radar-deck-card[data-slot="mid"] {
    transform: translateY(-10px) translateX(4px) scale(0.94);
    opacity: 0.3;
    filter: grayscale(50%);
  }
  ```

- [ ] **Step 2: Verify build passes**

  ```bash
  npm run build
  ```
  Expected: `✓ Compiled successfully`.

---

## Task 3 — Add card content CSS (rdc-*) and nav CSS to globals.css

**File:** `src/app/globals.css`

Append immediately after the block added in Task 2.

- [ ] **Step 1: Append card content styles**

  ```css
  /* ─ Card clickable header zone ─ */

  .rdc-clickable {
    cursor: pointer;
  }

  .rdc-clickable:focus-visible {
    outline: 2px solid oklch(0.428 0.198 256);
    outline-offset: 3px;
    border-radius: 4px;
  }

  /* ─ Header row: time + prep badge ─ */

  .rdc-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--space-2);
  }

  .rdc-time-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--color-ink-2);
  }

  .rdc-day   { color: var(--color-ink); }
  .rdc-dot   { color: var(--color-ink-placeholder); }
  .rdc-time  { color: var(--color-ink-2); }
  .rdc-relative { color: var(--color-ink-placeholder); }

  /* ─ Title row ─ */

  .rdc-title-row {
    font-size: 15px;
    font-weight: 600;
    color: var(--color-ink);
    margin-bottom: var(--space-1);
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 0;
  }

  .rdc-account      { color: var(--color-ink); }
  .rdc-sep          { color: var(--color-ink-placeholder); }
  .rdc-meeting-name { color: var(--color-ink-2); font-weight: 500; }

  /* ─ Meta row ─ */

  .rdc-meta-row {
    font-size: 12px;
    color: var(--color-ink-placeholder);
    margin-top: var(--space-1);
  }

  /* ─ Expand zone (grid-template-rows trick) ─ */

  .rdc-expand {
    display: grid;
    grid-template-rows: 0fr;
    transition: grid-template-rows 350ms var(--ease-out-expo);
  }

  .radar-deck-card.is-open .rdc-expand {
    grid-template-rows: 1fr;
  }

  .rdc-expand-inner {
    overflow: hidden;
  }

  /* Separator + padding for briefing content */
  .rdc-briefing-wrap {
    border-top: 1px solid var(--color-border-subtle);
    margin-top: var(--space-3);
    padding-top: var(--space-4);
  }

  /* ─ Expand footer with close button ─ */

  .rdc-expand-footer {
    display: flex;
    justify-content: flex-end;
    padding: var(--space-3) 0 var(--space-2);
    border-top: 1px solid var(--color-border-subtle);
    margin-top: var(--space-4);
  }

  .rdc-close-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-size: 12px;
    font-weight: 500;
    color: var(--color-ink-2);
    background: none;
    border: none;
    cursor: pointer;
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    font-family: inherit;
    transition:
      color      var(--dur-fast) var(--ease-out-quart),
      background var(--dur-fast) var(--ease-out-quart);
  }

  .rdc-close-btn:hover {
    color: var(--color-ink);
    background: var(--color-surface);
  }
  ```

- [ ] **Step 2: Append nav styles**

  ```css
  /* ─ Deck navigation ─ */

  .radar-deck-nav {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-5) var(--space-4);
    border-top: 1px solid var(--color-border-subtle);
  }

  .rdn-arrow {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    background: none;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    cursor: pointer;
    color: var(--color-ink-2);
    font-family: inherit;
    transition:
      color      var(--dur-fast) var(--ease-out-quart),
      background var(--dur-fast) var(--ease-out-quart),
      transform  100ms          var(--ease-out-quart);
  }

  .rdn-arrow--prev:hover:not(:disabled) {
    color: var(--color-ink);
    background: var(--color-surface);
    transform: translateX(-2px);
  }

  .rdn-arrow--next:hover:not(:disabled) {
    color: var(--color-ink);
    background: var(--color-surface);
    transform: translateX(2px);
  }

  .rdn-arrow:disabled {
    opacity: 0.32;
    cursor: default;
  }

  .rdn-counter {
    font-size: 12px;
    font-weight: 500;
    color: var(--color-ink-2);
    min-width: 44px;
    text-align: center;
    font-variant-numeric: tabular-nums;
  }

  /* ─ Reduced motion: disable all deck transitions ─ */

  @media (prefers-reduced-motion: reduce) {
    .radar-deck-card,
    .radar-deck-card[data-slot="front"],
    .rdc-expand {
      transition: none;
    }
  }
  ```

- [ ] **Step 3: Verify build passes**

  ```bash
  npm run build
  ```
  Expected: `✓ Compiled successfully`.

- [ ] **Step 4: Commit CSS changes**

  ```bash
  git add src/app/globals.css
  git commit -m "feat: add radar deck stack CSS — layout, transforms, animations, nav"
  ```

---

## Task 4 — Add ChevronLeftIcon and ChevronUpIcon to page.js

**File:** `src/app/workspace/page.js`

Two new icon components are needed: `ChevronLeftIcon` (nav prev arrow) and `ChevronUpIcon` (close button). Add them in the `/* ── ICONS ──── */` section at the bottom of the file, after the existing `ChevronDownIcon`.

- [ ] **Step 1: Locate the icons section**

  Find `function ChevronDownIcon()` near the bottom of `workspace/page.js` (around line 691).

- [ ] **Step 2: Add the two new icons after `ChevronDownIcon`**

  After the closing `}` of `ChevronDownIcon`, add:

  ```jsx
  function ChevronLeftIcon() {
    return (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
        aria-hidden="true" style={{ flexShrink: 0 }}>
        <path d="m15 18-6-6 6-6"/>
      </svg>
    );
  }

  function ChevronUpIcon() {
    return (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
        aria-hidden="true" style={{ flexShrink: 0 }}>
        <path d="m18 15-6-6-6 6"/>
      </svg>
    );
  }
  ```

- [ ] **Step 3: Verify build passes**

  ```bash
  npm run build
  ```
  Expected: `✓ Compiled successfully`.

---

## Task 5 — Write RadarDeckNav component

**File:** `src/app/workspace/page.js`

Add `RadarDeckNav` in the `/* ── SHARED ── */` section, before `RadarRow`. It renders `‹ 2 / 5 ›` with disabled-state arrow buttons.

- [ ] **Step 1: Add RadarDeckNav above the existing `RadarRow` function**

  Find `/* ── SHARED: RADAR ROW ── */` (around line 543). Insert before it:

  ```jsx
  /* ── SHARED: RADAR DECK NAV ───────────────────────────────── */

  function RadarDeckNav({ activeIndex, total, onPrev, onNext }) {
    return (
      <div className="radar-deck-nav">
        <button
          className="rdn-arrow rdn-arrow--prev"
          onClick={onPrev}
          disabled={activeIndex === 0}
          aria-label="Previous meeting"
        >
          <ChevronLeftIcon />
        </button>
        <span className="rdn-counter" aria-live="polite">
          {activeIndex + 1} / {total}
        </span>
        <button
          className="rdn-arrow rdn-arrow--next"
          onClick={onNext}
          disabled={activeIndex === total - 1}
          aria-label="Next meeting"
        >
          <ChevronRightIcon />
        </button>
      </div>
    );
  }
  ```

- [ ] **Step 2: Verify build passes**

  ```bash
  npm run build
  ```
  Expected: `✓ Compiled successfully`.

---

## Task 6 — Write RadarDeckCard component

**File:** `src/app/workspace/page.js`

Add `RadarDeckCard` immediately after `RadarDeckNav`. It renders either a ghost (empty placeholder) or a full card depending on whether `meeting` is null.

- [ ] **Step 1: Add RadarDeckCard after RadarDeckNav**

  ```jsx
  /* ── SHARED: RADAR DECK CARD ──────────────────────────────── */

  function RadarDeckCard({ meeting, slot, open, onToggle }) {
    const isFront = slot === 'front';

    const chipClass = meeting ? ({
      'ready':       'radar-prep--ready',
      'in-progress': 'radar-prep--progress',
      'cold':        'radar-prep--cold',
    }[meeting.prepStatus] || 'radar-prep--progress') : '';

    const handleKeyDown = (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onToggle();
      }
    };

    // Ghost card — visual depth only, no content
    if (!meeting) {
      return (
        <div
          className="radar-deck-card"
          data-slot={slot}
          aria-hidden="true"
        />
      );
    }

    return (
      <div
        className={`radar-deck-card${open ? ' is-open' : ''}`}
        data-slot={slot}
        aria-hidden={!isFront ? 'true' : undefined}
        tabIndex={-1}
      >
        {/* Clickable zone: header + title + meta only */}
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

        {/* Expand zone: only rendered on front card */}
        {isFront && (
          <div className="rdc-expand">
            <div className="rdc-expand-inner">
              <div className="rdc-briefing-wrap">
                <RadarBriefingPanel meeting={meeting} />
              </div>
              <div className="rdc-expand-footer">
                <button
                  className="rdc-close-btn"
                  onClick={onToggle}
                  aria-label="Close briefing"
                >
                  Close <ChevronUpIcon />
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }
  ```

- [ ] **Step 2: Verify build passes**

  ```bash
  npm run build
  ```
  Expected: `✓ Compiled successfully`.

---

## Task 7 — Write RadarDeckStack component

**File:** `src/app/workspace/page.js`

Add `RadarDeckStack` after `RadarDeckCard`. It owns `activeIndex` and `open` state, derives the three card slots, and wires close-then-navigate logic.

- [ ] **Step 1: Add RadarDeckStack after RadarDeckCard**

  ```jsx
  /* ── SHARED: RADAR DECK STACK ─────────────────────────────── */

  function RadarDeckStack({ meetings }) {
    const [activeIndex, setActiveIndex] = useState(0);
    const [open, setOpen] = useState(false);

    const navigate = (newIndex) => {
      if (open) {
        // Close first, then switch after the close transition finishes (260ms)
        setOpen(false);
        setTimeout(() => setActiveIndex(newIndex), 260);
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
          {/* Render back first (lowest z), then mid, then front */}
          <RadarDeckCard
            meeting={backMeeting}
            slot="back"
            open={false}
            onToggle={null}
          />
          <RadarDeckCard
            meeting={midMeeting}
            slot="mid"
            open={false}
            onToggle={null}
          />
          <RadarDeckCard
            meeting={frontMeeting}
            slot="front"
            open={open}
            onToggle={() => setOpen(o => !o)}
          />
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

  > **Note on the wrapper class:** The CSS uses `.deck-is-open .radar-deck-card[data-slot="back"]` etc. The wrapper `div` needs the `deck-is-open` class. Using `deck-is-open-wrapper` as the base class name avoids polluting `.radar-card`. Add this rule to globals.css in the same Task 3 block:

- [ ] **Step 2: Add the `.deck-is-open-wrapper` base style to globals.css**

  The wrapper needs no special base styles — it's just a container. The `.deck-is-open` class on it triggers the back/mid recede rules already written in Task 2. No additional CSS needed.

  However, double-check: the selector `.deck-is-open .radar-deck-card[data-slot="back"]` written in Task 2 needs the parent to have class `deck-is-open`. The component adds this to the `deck-is-open-wrapper` div. Confirm the selector chain: `.deck-is-open-wrapper.deck-is-open .radar-deck-card[data-slot="back"]` — this works since the CSS rule `.deck-is-open .radar-deck-card[data-slot="back"]` selects any `.radar-deck-card[data-slot="back"]` that is a descendant of an element with class `deck-is-open`.

- [ ] **Step 3: Verify build passes**

  ```bash
  npm run build
  ```
  Expected: `✓ Compiled successfully`.

---

## Task 8 — Update WeeklyRadarCard and verify full feature

**File:** `src/app/workspace/page.js`

Replace the `.radar-meetings` div (which maps `RADAR_MEETINGS` to `RadarRow`) with `<RadarDeckStack meetings={RADAR_MEETINGS} />`. Update the meta text. Keep `RadarRow` — it's still used by `NewbieRadarCard`.

- [ ] **Step 1: Update WeeklyRadarCard**

  Find this block in `WeeklyRadarCard` (around line 285):

  ```jsx
  function WeeklyRadarCard() {
    const prepped    = RADAR_MEETINGS.filter(m => m.prepStatus === 'ready').length;
    const inProgress = RADAR_MEETINGS.filter(m => m.prepStatus === 'in-progress').length;
    const cold       = RADAR_MEETINGS.filter(m => m.prepStatus === 'cold').length;

    return (
      <div className="radar-card">
        <div className="radar-header">
          <div className="radar-header-row">
            <h2 className="radar-title">Weekly Radar</h2>
            <div className="radar-status-chips">
              {prepped > 0    && <span className="radar-chip radar-chip--ready">{prepped} Prepped</span>}
              {inProgress > 0 && <span className="radar-chip radar-chip--progress">{inProgress} In Progress</span>}
              {cold > 0       && <span className="radar-chip radar-chip--cold">{cold} Cold</span>}
            </div>
          </div>
          <div className="radar-meta">Calendar sync · {RADAR_MEETINGS.length} meetings · Briefing opens inline</div>
        </div>
        <div className="radar-meetings">
          {RADAR_MEETINGS.map(m => <RadarRow key={m.id} meeting={m} />)}
        </div>
      </div>
    );
  }
  ```

  Replace with:

  ```jsx
  function WeeklyRadarCard() {
    const prepped    = RADAR_MEETINGS.filter(m => m.prepStatus === 'ready').length;
    const inProgress = RADAR_MEETINGS.filter(m => m.prepStatus === 'in-progress').length;
    const cold       = RADAR_MEETINGS.filter(m => m.prepStatus === 'cold').length;

    return (
      <div className="radar-card">
        <div className="radar-header">
          <div className="radar-header-row">
            <h2 className="radar-title">Weekly Radar</h2>
            <div className="radar-status-chips">
              {prepped > 0    && <span className="radar-chip radar-chip--ready">{prepped} Prepped</span>}
              {inProgress > 0 && <span className="radar-chip radar-chip--progress">{inProgress} In Progress</span>}
              {cold > 0       && <span className="radar-chip radar-chip--cold">{cold} Cold</span>}
            </div>
          </div>
          <div className="radar-meta">Calendar sync · {RADAR_MEETINGS.length} meetings · Click a card to open briefing</div>
        </div>
        <RadarDeckStack meetings={RADAR_MEETINGS} />
      </div>
    );
  }
  ```

- [ ] **Step 2: Run build**

  ```bash
  npm run build
  ```
  Expected: `✓ Compiled successfully`, zero ESLint errors.

  If you see `react/no-unescaped-entities` errors, fix them using `&apos;` for `'` and `&ldquo;`/`&rdquo;` for `"..."`.

- [ ] **Step 3: Start dev server and verify visually**

  ```bash
  npm run dev
  ```

  Open `http://localhost:3000/workspace` in a browser. In VETERAN mode, verify:
  - The Weekly Radar shows a stacked deck (3 cards visible, back/mid peeking above, front skewed)
  - Hovering the front card shows a subtle shadow
  - Clicking the front card: card de-skews + briefing expands smoothly
  - Close button collapses the briefing
  - Nav arrows `‹ 1 / 3 ›` are present; next arrow advances to meeting 2, back card changes
  - At index 0: prev arrow is disabled; at index 2 (last): next arrow is disabled
  - If a card is open and you click nav, briefing closes first, then card switches
  - In NEWBIE mode: the page is unaffected (newbie radar still shows flat `RadarRow` list)

- [ ] **Step 4: Commit final implementation**

  ```bash
  git add src/app/workspace/page.js src/app/globals.css
  git commit -m "feat: replace radar row list with stacked deck card + in-card briefing expand"
  ```

---

## Self-Review

**Spec coverage:**
- ✅ N-meeting support via `activeIndex` + nav
- ✅ 3 visible slots (front/mid/back) with ghost card for out-of-bounds
- ✅ Full-width cards with CSS transform depth illusion
- ✅ Front card de-skews on open (350ms ease-out-expo)
- ✅ Content reveals via grid-template-rows trick
- ✅ `RadarBriefingPanel` reused unchanged
- ✅ Back/mid recede on open (200ms ease-out-quart)
- ✅ Close-then-navigate sequence (260ms gap)
- ✅ Nav arrows with disabled-at-bounds, linear navigation
- ✅ `aria-expanded`, `role="button"`, keyboard Enter/Space on front card
- ✅ Back/mid `aria-hidden="true"`, `pointer-events: none`
- ✅ `aria-live="polite"` on counter
- ✅ `prefers-reduced-motion` disables all deck transitions
- ✅ `NewbieRadarCard` untouched (still uses `RadarRow`)
- ✅ `RadarRow` preserved

**Placeholder scan:** No TBD or TODO in any step. All code blocks are complete.

**Type consistency:** `RadarDeckStack` passes `meetings` array → `RadarDeckCard` receives `meeting` (single item or null). `RadarDeckNav` receives `activeIndex`, `total`, `onPrev`, `onNext` — consistent across Task 5 (definition) and Task 7 (usage).
