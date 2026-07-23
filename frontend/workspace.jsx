// ============================================================
// CS Platform · Workspace page  ·  v4 update
// Ego Trap hero · Weekly Radar (with inline Mission Briefing
// that expands from each meeting card) · Tests · Drops/Bloom
// ============================================================

const { useState: useStateW } = React;

function Workspace({ persona, heroLayout }) {
  const layout = heroLayout || "egotrap-first";
  return (
    <div className="page">
      <PageHead persona={persona} />
      <div className={`ws-grid ${layout === "radar-first" ? "radar-first" : ""} ${layout === "split" ? "split" : ""}`}>
        <div className="ws-main">
          {persona === "veteran" ? <EgoTrap /> : <NewbieTrackHero />}
          {persona === "veteran" ? <WeeklyRadar /> : <NewbieRadar />}
        </div>
        <div className="ws-side">
          <TestQueue persona={persona} />
          {persona === "newbie" ? <BloomCard /> : <KnowledgeDrops />}
        </div>
      </div>
    </div>
  );
}

function PageHead({ persona }) {
  return (
    <div className="page-head">
      <div>
        <div className="page-eyebrow">Workspace · Today</div>
        <h1 className="page-title">
          {persona === "veteran"
            ? "Good morning, Priya. Two meetings on the deck."
            : "Welcome back, Riya. You're 41 days into your track."}
        </h1>
        <p className="page-sub">
          {persona === "veteran"
            ? "The Ego Trap fires every day. Account A renewal is in 2 days — open the briefing in your Radar below."
            : "Phase 2 of 3 — Understand. Three modules and one Apply simulation queued for today."}
        </p>
      </div>
      <div className="page-actions">
        <button className="btn ghost"><Icon name="files" /> Account A · Renewal</button>
        <button className="btn"><Icon name="plus" /> New scratch note</button>
      </div>
    </div>
  );
}

// ---------- Ego Trap (veteran) ----------
function EgoTrap() {
  const [open, setOpen] = useStateW(!!window.__PRINT_MODE__);
  return (
    <section className={`ego ${open ? "" : "compact"}`}>
      <div className="ego-banner">
        <span className="dot" />
        <span>Ego Trap · Fires every day</span>
        <span style={{ marginLeft: "auto", color: "var(--fg-faint)" }}>Generated 07:42 IST · transcript processed</span>
      </div>

      <div className="ego-head" onClick={() => setOpen(!open)} style={{ cursor: "pointer" }}>
        <div className="ego-head-main">
          <h2 className="ego-title">Your Account D renewal call on Tue — how did it go?</h2>
          <p className="ego-sub">
            2 moments applied · 2 moments missed · cross-referenced against 14 modules and 9 failure stories.
          </p>
          <div className="ego-meta">
            <span><Icon name="clock" size={12} /> 38m 22s</span>
            <span><Icon name="waveform" size={12} /> transcript · auto</span>
            <span><Icon name="user" size={12} /> 2 participants</span>
          </div>
        </div>
        <div className="h-stack" style={{ flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
          <span className="badge accent">Mirror · not a score</span>
          <button className="btn sm" onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>
            {open ? <>Hide mirror <Icon name="chevronDown" size={12} /></> : <>View mirror <Icon name="chevron" size={12} /></>}
          </button>
        </div>
      </div>

      {open && <>
      <div className="ego-mirror">
        <div className="ego-side applied">
          <div className="ego-side-head">
            <span>What you applied</span>
            <span className="count">3</span>
          </div>
          <Moment
            time="14:32"
            quote="You reframed from CPH to brand visibility — the exact technique from the FMCG Renewal Playbook. Cleanly executed."
            source="FMCG Renewal Playbook · Module 4 · §2.3"
          />
          <Moment
            time="21:04"
            quote="You named the lifecycle stage before proposing the upsell — Aryan's framing from the Q2 Living Case Study."
            source="Living Case Study · Account M · Ch 3"
          />
        </div>
        <div className="ego-side missed">
          <div className="ego-side-head">
            <span>What you missed</span>
            <span className="count">2</span>
          </div>
          <Moment
            time="22:18"
            quote="Ankit said he'd 'been looking at alternatives'. You treated it as a vendor comparison. The Failure Library has this exact pattern — Project Atlas, Month 4."
            source="Failure Library · Project Atlas · Ch 4"
          />
          <Moment
            time="31:50"
            quote="Engagement dropped to one-word answers for the last 6 minutes — you didn't acknowledge the disengagement signal."
            source="Module: Reading the room · §3"
          />
        </div>
      </div>

      <div className="ego-foot">
        <span className="ego-breadcrumb">
          The full post-mortem on this pattern is in the <b>Failure Library</b>
          <Icon name="arrow" size={14} />
        </span>
        <div className="h-stack">
          <button className="btn ghost"><Icon name="play" size={12} /> Replay 22:18</button>
          <button className="btn primary">Practice this in the Simulator <Icon name="arrow" size={14} /></button>
        </div>
      </div>
      </>}
    </section>
  );
}

function Moment({ time, quote, source }) {
  return (
    <div className="moment">
      <div className="moment-time">{time}</div>
      <div className="moment-body">
        <p className="moment-quote">{quote}</p>
        <div className="moment-source">{source}</div>
      </div>
      <button className="moment-play" aria-label="Play clip"><Icon name="play" size={9} /></button>
    </div>
  );
}

// ---------- Newbie Track hero ----------
function NewbieTrackHero() {
  const [open, setOpen] = useStateW(!!window.__PRINT_MODE__);
  return (
    <section className={`ego ${open ? "" : "compact"}`}>
      <div className="ego-banner">
        <span className="dot" />
        <span>3-Month Mandatory Track · Phase 2 of 3</span>
        <span style={{ marginLeft: "auto", color: "var(--fg-faint)" }}>Day 41 / 90 · Bloom: Understand</span>
      </div>

      <div className="ego-head" onClick={() => setOpen(!open)} style={{ cursor: "pointer" }}>
        <div className="ego-head-main">
          <h2 className="ego-title">Phase 2 · Understand — 46% complete</h2>
          <p className="ego-sub">
            One module and one case study queued for today. Apply simulations unlock when this phase finishes.
          </p>
          <div className="track-progress" style={{ marginTop: 14 }}>
            <div className="track-bar">
              <div className="track-bar-fill" style={{ width: "46%" }} />
            </div>
            <div className="track-phases">
              <div className="track-phase done">Phase 1 <b>Remember</b></div>
              <div className="track-phase active">Phase 2 <b>Understand</b></div>
              <div className="track-phase">Phase 3 <b>Apply</b></div>
            </div>
          </div>
        </div>
        <button className="btn sm" onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>
          {open ? <>Hide <Icon name="chevronDown" size={12} /></> : <>What's next <Icon name="chevron" size={12} /></>}
        </button>
      </div>

      {open && <>
      <div className="ego-mirror" style={{ gridTemplateColumns: "1fr" }}>
        <div className="ego-side">
          <div className="ego-side-head" style={{ color: "var(--fg-mute)" }}>
            <span>Next up · today</span>
          </div>
          <Moment
            time="Module"
            quote="Account lifecycle stages — onboarding, growth, plateau, renewal. What the signals look like at each stage."
            source="Phase 2 · Understand · 12 min · 3 MCQ"
          />
          <Moment
            time="Case"
            quote="Aryan's Account A: a healthy renewal. Annotated clips at the 6 key decision points."
            source="Case Study · Account A · 18 min"
          />
        </div>
      </div>

      <div className="ego-foot">
        <span className="ego-breadcrumb">
          The track <b>cannot be skipped</b>. Personalisation unlocks at day 90.
          <Icon name="arrow" size={14} />
        </span>
        <button className="btn primary">Resume Phase 2 <Icon name="arrow" size={14} /></button>
      </div>
      </>}
    </section>
  );
}

// ============================================================
//  Weekly Radar v4 — with inline Mission Briefing per card
// ============================================================

function WeeklyRadar() {
  const meetings = [
    {
      id: "wed-acct-a",
      day: "Wed", time: "2:30 PM", relative: "in 2 days",
      client: "Account A · Renewal review",
      type: "QBR · CXO + Director · APAC",
      industry: "FMCG · 11 months active",
      prepStatus: "in-progress",
      prepLabel: "Prep · 1 of 3",
      clip: {
        quote: "Lead with the 90-day brand-visibility delta, not CPH.",
        meta: "Sarah · QBR · Account B · Q3 2025 · 02:14",
      },
      tip: "Account A's apply rate dipped 12% in the last 30 days while CPH dropped 8%. Likely a quality-conscious procurement cycle, not a churn signal — open with brand visibility, hold ROI for the second half.",
      waterfall: [
        { state: "done",   label: "FMCG renewal narrative",  meta: "8 min · scored 92%",   kind: "Module" },
        { state: "active", label: "Account J · 18-month arc", meta: "3 chapters · 12 min",  kind: "Case Study" },
        { state: "lock",   label: "Project Atlas · Month 4",  meta: "Unlocks after Step 2", kind: "Failure" },
      ],
    },
    {
      id: "thu-acct-f",
      day: "Thu", time: "10:00 AM", relative: "in 3 days",
      client: "Account F · Mid-month sync",
      type: "Working session · Talent Acquisition lead",
      industry: "Staffing · 8 months active",
      prepStatus: "done",
      prepLabel: "You're prepped",
      clip: { quote: "Open with the time-to-fill delta. Engagement, second.", meta: "Aryan · sync · Account J · Q1 2026 · 01:48" },
      tip: "Account F's TTF is 4 days under target. Stakeholder responsiveness is the bottleneck — bring three concrete asks.",
      waterfall: [
        { state: "done", label: "Mid-month sync rhythm",   meta: "5 min · scored 96%", kind: "Module" },
        { state: "done", label: "Account J · Chapter 2",   meta: "Read · 6 min",       kind: "Case Study" },
        { state: "done", label: "Account E · ghost cycle", meta: "Read · 4 min",       kind: "Failure" },
      ],
    },
    {
      id: "fri-acct-k",
      day: "Fri", time: "4:00 PM", relative: "in 4 days",
      client: "Account K · Escalation",
      type: "Re-engagement · CFO · second meeting",
      industry: "RPO · 14 months active · at risk",
      prepStatus: "cold",
      prepLabel: "Prep · 0 of 3",
      clip: { quote: "If the CFO opens, you've already lost the framing. Lead.", meta: "Priya · escalation · Account R · Q4 2025 · 01:22" },
      tip: "Account K hasn't responded to two re-engagement emails. Treat this as the 'last reasonable shot' meeting — the Failure Library has three precedents that died at exactly this point.",
      waterfall: [
        { state: "active", label: "CFO objection handles",   meta: "11 min · 1 MCQ", kind: "Module" },
        { state: "lock",   label: "Account R · two CXOs arc", meta: "Locked",         kind: "Case Study" },
        { state: "lock",   label: "Project Atlas · disengage", meta: "Locked",        kind: "Failure" },
      ],
    },
  ];

  const [openId, setOpenId] = useStateW(window.__PRINT_MODE__ ? meetings[0].id : null);
  return (
    <section className="radar">
      <div className="radar-head">
        <div>
          <h3 className="radar-title">Weekly Radar</h3>
          <div className="radar-sub">Calendar sync · 3 meetings · briefing opens inline</div>
        </div>
        <div className="h-stack">
          <span className="badge good">1 prepped</span>
          <span className="badge warn">1 in progress</span>
          <span className="badge bad">1 cold</span>
        </div>
      </div>

      {meetings.map((m) => (
        <MeetingCard
          key={m.id}
          meeting={m}
          open={openId === m.id}
          onToggle={() => setOpenId(openId === m.id ? null : m.id)}
        />
      ))}
    </section>
  );
}

function MeetingCard({ meeting, open, onToggle }) {
  const m = meeting;
  const prepBadge =
    m.prepStatus === "done" ? <span className="badge good">{m.prepLabel}</span> :
    m.prepStatus === "in-progress" ? <span className="badge warn">{m.prepLabel}</span> :
    <span className="badge bad">{m.prepLabel}</span>;

  return (
    <div className={`meeting-wrap ${open ? "open" : ""}`}>
      <article className={`meeting ${open ? "hero" : ""}`} onClick={onToggle}>
        <div className="meeting-when">
          <span>{m.day}</span>
          <b>{m.time}</b>
          <span style={{ color: "var(--accent-fg)" }}>{m.relative}</span>
        </div>
        <div className="meeting-main">
          <h4 className="meeting-client">{m.client}</h4>
          <div className="meeting-type">{m.type}</div>
        </div>
        <div className="meeting-prep">
          {prepBadge}
          <button className="btn sm ghost" onClick={(e) => { e.stopPropagation(); onToggle(); }}>
            {open ? <>Hide briefing <Icon name="chevronDown" size={12} /></> : <>Open briefing <Icon name="chevron" size={12} /></>}
          </button>
        </div>
      </article>

      {open && (
        <div className="meeting-briefing">
          <div className="meeting-briefing-grid">
            <div className="meeting-briefing-clip">
              <div className="card-eyebrow" style={{ marginBottom: 8 }}>Expert clip · 2 min</div>
              <div className="clip" style={{ marginBottom: 12 }}>
                <button className="clip-play" aria-label="Play"><Icon name="play" size={10} /></button>
                <div className="clip-meta">
                  <div className="clip-title">"{m.clip.quote}"</div>
                  <div className="clip-source">{m.clip.meta}</div>
                </div>
                <Waveform seed={m.day.length + 1} count={20} />
              </div>

              <div className="card-eyebrow" style={{ marginBottom: 8 }}>AI tip · account health</div>
              <div className="tip">
                <div className="tip-icon"><Icon name="sparkle" size={12} /></div>
                <div className="tip-body">
                  <p>{m.tip}</p>
                </div>
              </div>
            </div>

            <div className="meeting-briefing-waterfall">
              <div className="row between" style={{ marginBottom: 8 }}>
                <div className="card-eyebrow">Mission Briefing · locked sequence</div>
                <span className="card-eyebrow" style={{ color: "var(--fg-faint)" }}>{m.industry}</span>
              </div>
              <div className="waterfall vertical">
                {m.waterfall.map((step, i) => (
                  <div key={i} className={`wf-step ${step.state}`}>
                    <div className="wf-step-num">
                      <span>Step {String(i + 1).padStart(2, "0")} · {step.kind}</span>
                      {step.state === "done"   && <Icon name="check" size={12} />}
                      {step.state === "lock"   && <Icon name="lock" size={12} />}
                      {step.state === "active" && <span className="badge accent" style={{ padding: "2px 6px", fontSize: 9 }}>Now</span>}
                    </div>
                    <div className="wf-step-title">{step.label}</div>
                    <div className="wf-step-meta">{step.meta}</div>
                  </div>
                ))}
              </div>
              <div className="row between" style={{ marginTop: 12 }}>
                <span className="ego-breadcrumb" style={{ fontSize: 12 }}>
                  Once the waterfall is done, this card flips to <b>You're prepped</b>.
                </span>
                {m.prepStatus !== "done" && (
                  <button className="btn primary sm">
                    {m.prepStatus === "cold" ? "Start Step 01" : "Continue Step 02"}
                    <Icon name="arrow" size={12} />
                  </button>
                )}
                {m.prepStatus === "done" && (
                  <span className="badge good"><Icon name="check" size={11} /> Ready to walk in</span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------- Newbie radar variant ----------
function NewbieRadar() {
  const [open, setOpen] = useStateW(!!window.__PRINT_MODE__);
  return (
    <section className="radar">
      <div className="radar-head">
        <div>
          <h3 className="radar-title">Your week</h3>
          <div className="radar-sub">Your first calls are sit-ins — Aryan is the lead</div>
        </div>
        <span className="badge accent">Mandatory track prep</span>
      </div>

      <div className={`meeting-wrap ${open ? "open" : ""}`}>
        <article className={`meeting ${open ? "hero" : ""}`} onClick={() => setOpen(!open)}>
          <div className="meeting-when"><span>Tue</span><b>11:00 AM</b><span>in 1 day</span></div>
          <div className="meeting-main">
            <h4 className="meeting-client">Account A · Sit-in (lead: Aryan)</h4>
            <div className="meeting-type">Renewal · listen-only · take notes in side panel</div>
          </div>
          <div className="meeting-prep">
            <span className="badge warn">Prep · 0 of 2</span>
            <button className="btn sm ghost">{open ? "Hide briefing" : "Open briefing"}</button>
          </div>
        </article>
        {open && (
          <div className="meeting-briefing">
            <div className="meeting-briefing-grid">
              <div>
                <div className="card-eyebrow" style={{ marginBottom: 8 }}>Aryan's setup · 2 min</div>
                <div className="clip" style={{ marginBottom: 12 }}>
                  <button className="clip-play"><Icon name="play" size={10} /></button>
                  <div className="clip-meta">
                    <div className="clip-title">"Here's how I'm framing tomorrow — listen for the lifecycle pivot."</div>
                    <div className="clip-source">Aryan · prep note · Account A · 02:08</div>
                  </div>
                  <Waveform seed={5} count={20} />
                </div>
                <div className="tip">
                  <div className="tip-icon"><Icon name="sparkle" size={12} /></div>
                  <div className="tip-body">
                    <p><b>Prep before tomorrow.</b> Phase 2 module <i>"Account lifecycle stages"</i> is the foundation for what Aryan will demonstrate. 12 minutes. The mandatory test that follows takes 5.</p>
                  </div>
                </div>
              </div>
              <div>
                <div className="row between" style={{ marginBottom: 8 }}>
                  <div className="card-eyebrow">Mandatory track · pinned</div>
                  <span className="badge accent">Phase 2</span>
                </div>
                <div className="waterfall vertical">
                  <div className="wf-step active">
                    <div className="wf-step-num">
                      <span>Step 01 · Module</span>
                      <span className="badge accent" style={{ padding: "2px 6px", fontSize: 9 }}>Now</span>
                    </div>
                    <div className="wf-step-title">Account lifecycle stages</div>
                    <div className="wf-step-meta">12 min · 3 MCQ · mandatory</div>
                  </div>
                  <div className="wf-step locked">
                    <div className="wf-step-num">
                      <span>Step 02 · MCQ</span>
                      <Icon name="lock" size={12} />
                    </div>
                    <div className="wf-step-title">Short check · 5 questions</div>
                    <div className="wf-step-meta">Unlocks after module</div>
                  </div>
                </div>
                <div className="row between" style={{ marginTop: 12 }}>
                  <span className="ego-breadcrumb" style={{ fontSize: 12 }}>
                    Completes the briefing AND track Phase 2 module 3 — <b>double-credit</b>.
                  </span>
                  <button className="btn primary sm">Start <Icon name="arrow" size={12} /></button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      <article className="meeting">
        <div className="meeting-when"><span>Wed</span><b>3:00 PM</b><span>in 2 days</span></div>
        <div className="meeting-main">
          <h4 className="meeting-client">Cohort sync · Track checkpoint</h4>
          <div className="meeting-type">Internal · weekly cohort review</div>
        </div>
        <div className="meeting-prep"><span className="badge">Internal</span></div>
      </article>
    </section>
  );
}

// ---------- Test Queue side card ----------
function TestQueue({ persona }) {
  const veteranTests = [
    { state: "done",   title: "Diagnosis · Staffing health signals", meta: "Tier 1 · Analyse · scored 86" },
    { state: "active", title: "QBR Defense · skeptical CXO panel",   meta: "Tier 2 · Evaluate · 18 min · floated to top — Account A QBR in 2d" },
    { state: "lock",   title: "Post-mortem · churned RPO account",   meta: "Tier 2 · Analyse · 25 min" },
    { state: "lock",   title: "Solution pitch · new ATS integration", meta: "Tier 3 · Create · 22 min" },
  ];
  const newbieTests = [
    { state: "done",   title: "Joveo terminology · 50 cards",     meta: "Phase 1 · Remember" },
    { state: "done",   title: "Account types · scenario MCQs",    meta: "Phase 1 · Remember" },
    { state: "active", title: "Signals & lifecycle · short MCQ",  meta: "Phase 2 · Understand · 5 min · floats to top — Account A sit-in tomorrow" },
    { state: "lock",   title: "Apply: managing Account A early",  meta: "Phase 3 · unlocks after Phase 2" },
  ];
  const tests = persona === "veteran" ? veteranTests : newbieTests;
  return (
    <div className="side-card">
      <div className="side-card-head">
        <div>
          <div className="side-card-title">Test queue</div>
          <div className="card-eyebrow" style={{ marginTop: 2 }}>
            {persona === "veteran" ? "Waterfall · tier 2 of 3" : "Fixed · mandatory until day 90"}
          </div>
        </div>
        <button className="btn sm ghost">View all</button>
      </div>
      <div>
        {tests.map((t, i) => (
          <div key={i} className={`test-row ${t.state === "lock" ? "locked" : ""}`}>
            <div className={`test-mark ${t.state}`}>
              {t.state === "done" && <Icon name="check" size={11} />}
              {t.state === "lock" && <Icon name="lock" size={10} />}
            </div>
            <div className="test-main">
              <div className="test-title">{t.title}</div>
              <div className="test-meta">{t.meta}</div>
            </div>
            {t.state === "active" && <button className="btn sm">Take</button>}
          </div>
        ))}
      </div>
    </div>
  );
}

function BloomCard() {
  return (
    <div className="side-card">
      <div className="side-card-head">
        <div className="side-card-title">Bloom's · your path</div>
        <span className="badge accent">Newbie</span>
      </div>
      <div className="v-stack" style={{ gap: 8 }}>
        {[
          { l: "Remember",   state: "done",   note: "Terms, glossary, practices" },
          { l: "Understand", state: "active", note: "Signals, lifecycle, why" },
          { l: "Apply",      state: "next",   note: "Sim · controlled scenarios" },
          { l: "Analyse · Evaluate · Create", state: "lock", note: "Unlocks post-track" },
        ].map((b, i) => (
          <div key={i} className="row" style={{ padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 6, background: b.state === "active" ? "var(--accent-soft)" : "var(--bg-elev-2)", borderColor: b.state === "active" ? "var(--accent-line)" : undefined }}>
            <div style={{ width: 18, height: 18, borderRadius: "50%", background: b.state === "done" ? "var(--good)" : b.state === "active" ? "var(--accent)" : "var(--bg-sunken)", display: "grid", placeItems: "center", flexShrink: 0, color: "var(--bg-elev-1)" }}>
              {b.state === "done" ? <Icon name="check" size={10} /> : b.state === "lock" ? <Icon name="lock" size={9} /> : null}
            </div>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 12.5, fontWeight: 500 }}>{b.l}</div>
              <div className="card-eyebrow" style={{ marginTop: 1 }}>{b.note}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function KnowledgeDrops() {
  const items = [
    { tag: "New module", title: "Reframing CPH → brand visibility — 2-min recap", meta: "Released today · relevant to 4 of your accounts" },
    { tag: "Chapter 4",  title: "Account M · 'things got messy in the QBR'",      meta: "Living Case Study · 12 min" },
    { tag: "Failure",    title: "Project Atlas Month 4 — disengagement signals",  meta: "Similar to Account A · your renewal" },
  ];
  return (
    <div className="side-card">
      <div className="side-card-head">
        <div className="side-card-title">Knowledge drops</div>
        <span className="card-eyebrow">3 new</span>
      </div>
      <div className="v-stack" style={{ gap: 10 }}>
        {items.map((d, i) => (
          <button key={i} className="row" style={{ padding: 10, border: "1px solid var(--line)", borderRadius: 8, background: "var(--bg-elev-2)", alignItems: "flex-start", gap: 10, width: "100%", textAlign: "left", cursor: "pointer" }}>
            <span className="badge" style={{ alignSelf: "flex-start" }}>{d.tag}</span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 12.5, fontWeight: 500, marginBottom: 2, lineHeight: 1.35 }}>{d.title}</div>
              <div className="card-eyebrow">{d.meta}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { Workspace });
