import type { EgoTrap, RadarMeeting, TestQueueItem, KnowledgeDrop, NewbieTrack, BloomStage } from "@/types";
/* ── VETERAN MOCK DATA ─────────────────────────────────────── */

export const EGO_TRAPS: EgoTrap[] = [
  {
    day: 'MON', account: 'Account B', meetingType: 'QBR',
    question: 'Your Account B QBR on Mon — did you lead with their scorecard or yours?',
    applied: 3, missed: 1, modules: 11, failureStories: 6,
    duration: '44M 10S', source: 'TRANSCRIPT · AUTO', participants: 3, generatedAt: '08:15 IST',
    appliedMoments: [
      {
        time: '08:22',
        quote: "You opened with their KPIs before introducing your metrics — exactly the 'their frame first' principle from QBR Mastery §1.",
        source: 'QBR Mastery · Module 2 · §1.1',
      },
      {
        time: '19:40',
        quote: 'You paused after the competitor mention instead of reacting — bought yourself space to redirect.',
        source: 'Living Case Study · Account J · Ch 2',
      },
      {
        time: '33:55',
        quote: "Named the risk before the client did — that's the pre-emption move from the FMCG Renewal Playbook.",
        source: 'FMCG Renewal Playbook · Module 6 · §3.1',
      },
    ],
    missedMoments: [
      {
        time: '27:14',
        quote: "The CFO asked about ROI timeline — you gave a range. The Failure Library shows ranges signal uncertainty and invite pushback.",
        source: 'Failure Library · Novo Nordisk · Ch 2',
      },
    ],
  },
  {
    day: 'MON', account: 'Sanofi', meetingType: 'Escalation call',
    question: "Sanofi's escalation call on Mon — were you solving the problem or managing perception?",
    applied: 1, missed: 3, modules: 9, failureStories: 7,
    duration: '29M 04S', source: 'TRANSCRIPT · AUTO', participants: 4, generatedAt: '16:30 IST',
    appliedMoments: [
      {
        time: '05:10',
        quote: "You acknowledged the delay before they raised it — reduced defensive tension in the first 5 minutes.",
        source: 'Module: Escalation Framing · §2',
      },
    ],
    missedMoments: [
      {
        time: '11:33',
        quote: "When the VP listed the failures, you jumped to solutions. The pattern in Project Atlas Ch 4 — they needed acknowledgment, not fixes.",
        source: 'Failure Library · Project Atlas · Ch 4',
      },
      {
        time: '18:20',
        quote: "You used 'we're working on it' three times. That phrase has zero information density and signals stalling.",
        source: 'Module: Escalation Framing · §4.2',
      },
      {
        time: '24:47',
        quote: "Left without a concrete next-step owner. Sanofi's VP will remember this as unresolved.",
        source: 'Living Case Study · Account R · Ch 5',
      },
    ],
  },
  {
    day: 'TUE', account: 'Account D', meetingType: 'Renewal call',
    question: 'Your Account D renewal call on Tue — how did it go?',
    applied: 2, missed: 2, modules: 14, failureStories: 9,
    duration: '38M 22S', source: 'TRANSCRIPT · AUTO', participants: 2, generatedAt: '07:42 IST',
    appliedMoments: [
      {
        time: '14:32',
        quote: 'You reframed from CPH to brand visibility — the exact technique from the FMCG Renewal Playbook. Cleanly executed.',
        source: 'FMCG Renewal Playbook · Module 4 · §2.3',
      },
      {
        time: '21:04',
        quote: "You named the lifecycle stage before proposing the upsell — Aryan's framing from the Q2 Living Case Study.",
        source: 'Living Case Study · Account M · Ch 3',
      },
    ],
    missedMoments: [
      {
        time: '22:18',
        quote: "Ankit said he'd 'been looking at alternatives'. You treated it as a vendor comparison. The Failure Library has this exact pattern — Project Atlas, Month 4.",
        source: 'Failure Library · Project Atlas · Ch 4',
      },
      {
        time: '31:50',
        quote: "Engagement dropped to one-word answers for the last 6 minutes — you didn't acknowledge the disengagement signal.",
        source: 'Module: Reading the room · §3',
      },
    ],
  },
  {
    day: 'WED', account: 'Account F', meetingType: 'Mid-month sync',
    question: "Account F sync on Wed — did you come with asks or just updates?",
    applied: 2, missed: 1, modules: 8, failureStories: 4,
    duration: '22M 48S', source: 'TRANSCRIPT · AUTO', participants: 2, generatedAt: '11:58 IST',
    appliedMoments: [
      {
        time: '03:45',
        quote: 'Opened with the TTF delta — led with their metric, not yours. Clean.',
        source: 'Module: Mid-month sync rhythm · §1',
      },
      {
        time: '14:20',
        quote: "You brought three concrete asks instead of vague next steps. That's the pattern from Account J Ch 2.",
        source: 'Living Case Study · Account J · Ch 2',
      },
    ],
    missedMoments: [
      {
        time: '18:02',
        quote: "The stakeholder said 'I'll loop in the team' — that's a soft block. You let it pass without probing.",
        source: 'Module: Reading the room · §2.1',
      },
    ],
  },
  {
    day: 'WED', account: 'Account A', meetingType: 'Pre-QBR check',
    question: "Your pre-QBR check with Account A on Wed — are you prepping or performing?",
    applied: 1, missed: 2, modules: 12, failureStories: 8,
    duration: '18M 33S', source: 'TRANSCRIPT · AUTO', participants: 2, generatedAt: '15:10 IST',
    appliedMoments: [
      {
        time: '07:55',
        quote: "You confirmed the decision-maker attendance before committing to QBR structure — smart gate.",
        source: 'QBR Mastery · Module 1 · §2',
      },
    ],
    missedMoments: [
      {
        time: '11:10',
        quote: "They flagged budget sensitivity — you stayed on the renewal pitch instead of shifting to value re-anchoring.",
        source: 'FMCG Renewal Playbook · Module 5 · §1.3',
      },
      {
        time: '15:40',
        quote: "Ended the call without confirming the pre-read was actually going to be read. Assumption of prep is a known failure mode.",
        source: 'Failure Library · Project Atlas · Ch 1',
      },
    ],
  },
];

export const RADAR_MEETINGS: RadarMeeting[] = [
  {
    id: 1, day: 'WED', time: '2:30 PM', relative: 'IN 2 DAYS',
    account: 'Account A', title: 'Renewal review',
    tags: 'QBR · CXO + Director · APAC',
    prepStatus: 'in-progress', prepLabel: 'PREP · 1 OF 3',
    industry: 'FMCG · 11 months active',
    clip: { quote: 'Lead with the 90-day brand-visibility delta, not CPH.', meta: 'Sarah · QBR · Account B · Q3 2025 · 02:14' },
    tip: "Account A's apply rate dipped 12% in the last 30 days while CPH dropped 8%. Likely a quality-conscious procurement cycle, not a churn signal — open with brand visibility, hold ROI for the second half.",
    waterfall: [
      { state: 'done',   kind: 'Module',     label: 'FMCG renewal narrative',   meta: '8 min · scored 92%'   },
      { state: 'active', kind: 'Case Study', label: 'Account J · 18-month arc', meta: '3 chapters · 12 min'  },
      { state: 'locked', kind: 'Failure',    label: 'Project Atlas · Month 4',  meta: 'Unlocks after Step 2' },
    ],
  },
  {
    id: 2, day: 'THU', time: '10:00 AM', relative: 'IN 3 DAYS',
    account: 'Account F', title: 'Mid-month sync',
    tags: 'Working session · Talent Acquisition lead',
    prepStatus: 'ready', prepLabel: "YOU'RE PREPPED",
    industry: 'Staffing · 8 months active',
    clip: { quote: 'Open with the time-to-fill delta. Engagement, second.', meta: 'Aryan · sync · Account J · Q1 2026 · 01:48' },
    tip: "Account F's TTF is 4 days under target. Stakeholder responsiveness is the bottleneck — bring three concrete asks.",
    waterfall: [
      { state: 'done', kind: 'Module',     label: 'Mid-month sync rhythm',  meta: '5 min · scored 96%' },
      { state: 'done', kind: 'Case Study', label: 'Account J · Chapter 2',  meta: 'Read · 6 min'       },
      { state: 'done', kind: 'Failure',    label: 'Account E · ghost cycle', meta: 'Read · 4 min'     },
    ],
  },
  {
    id: 3, day: 'FRI', time: '3:00 PM', relative: 'IN 4 DAYS',
    account: 'Sanofi', title: 'Onboarding check-in',
    tags: 'Week 4 activation · Job board connectivity',
    prepStatus: 'cold', prepLabel: 'NOT STARTED',
    industry: 'RPO · 14 months active',
    clip: { quote: "If the CFO opens, you've already lost the framing. Lead.", meta: 'Priya · escalation · Account R · Q4 2025 · 01:22' },
    tip: 'Sanofi is in week 4 of onboarding — job board connectivity is the core deliverable. Come in with a status checklist, not questions.',
    waterfall: [
      { state: 'active', kind: 'Module',     label: 'Onboarding activation signals', meta: '10 min · 1 MCQ' },
      { state: 'locked', kind: 'Case Study', label: 'Account R · onboarding arc',    meta: 'Locked'         },
      { state: 'locked', kind: 'Failure',    label: 'Project Atlas · disengage',     meta: 'Locked'         },
    ],
  },
];

export const TEST_QUEUE: TestQueueItem[] = [
  { id: 1, title: 'Diagnosis · Staffing health signals',  tier: 1, level: 'ANALYSE',  scored: 86,   status: 'complete', time: null,     note: null },
  { id: 2, title: 'QBR Defense · skeptical CXO panel',   tier: 2, level: 'EVALUATE', scored: null, status: 'active',   time: '18 MIN', note: 'FLOATED TO TOP – ACCOUNT A QBR IN 2D' },
  { id: 3, title: 'Post-mortem · churned RPO account',    tier: 2, level: 'ANALYSE',  scored: null, status: 'locked',   time: '25 MIN', note: null },
  { id: 4, title: 'Solution pitch · new ATS integration', tier: 3, level: 'CREATE',   scored: null, status: 'locked',   time: '22 MIN', note: null },
];

export const KNOWLEDGE_DROPS: KnowledgeDrop[] = [
  { id: 1, type: 'NEW MODULE',    title: 'Reframing CPH → brand ROI' },
  { id: 2, type: 'CASE STUDY',    title: 'How MedLine recovered from churn' },
  { id: 3, type: 'FAILURE STORY', title: 'The Novo Nordisk pricing misstep' },
];

/* ── NEWBIE MOCK DATA ──────────────────────────────────────── */

export const NEWBIE_TRACK: NewbieTrack = {
  day: 41, totalDays: 90, phase: 2, totalPhases: 3, phaseLabel: 'Understand', progress: 46,
  nextUp: [
    {
      kind: 'Module',
      desc: 'Account lifecycle stages — onboarding, growth, plateau, renewal. What the signals look like at each stage.',
      meta: 'Phase 2 · Understand · 12 min · 3 MCQ',
    },
    {
      kind: 'Case',
      desc: "Aryan's Account A: a healthy renewal. Annotated clips at the 6 key decision points.",
      meta: 'Case Study · Account A · 18 min',
    },
  ],
};

export const NEWBIE_RADAR_MEETINGS: RadarMeeting[] = [
  {
    id: 1, day: 'TUE', time: '11:00 AM', relative: 'IN 1 DAY',
    account: 'Account A', title: 'Sit-in (lead: Aryan)',
    tags: 'Renewal · listen-only · take notes in side panel',
    prepStatus: 'in-progress', prepLabel: 'PREP · 0 OF 2',
    industry: 'Mandatory track prep · Phase 2',
    clip: { label: "Aryan's setup · 2 min", quote: "Here's how I'm framing tomorrow — listen for the lifecycle pivot.", meta: 'Aryan · prep note · Account A · 02:08' },
    tip: "Prep before tomorrow. Phase 2 module 'Account lifecycle stages' is the foundation for what Aryan will demonstrate. 12 minutes. The mandatory test that follows takes 5.",
    waterfall: [
      { state: 'active', kind: 'Module', label: 'Account lifecycle stages',  meta: '12 min · 3 MCQ · mandatory' },
      { state: 'locked', kind: 'MCQ',    label: 'Short check · 5 questions', meta: 'Unlocks after module'        },
    ],
  },
];

export const NEWBIE_TEST_QUEUE: TestQueueItem[] = [
  { id: 1, title: 'Joveo terminology · 50 cards',    phase: 1, level: 'REMEMBER',   status: 'complete', time: null,    note: null },
  { id: 2, title: 'Account types · scenario MCQs',   phase: 1, level: 'REMEMBER',   status: 'complete', time: null,    note: null },
  { id: 3, title: 'Signals & lifecycle · short MCQ', phase: 2, level: 'UNDERSTAND', status: 'active',   time: '5 MIN', note: 'FLOATS TO TOP — ACCOUNT A SIT-IN TOMORROW' },
  { id: 4, title: 'Apply: managing Account A early', phase: 3, level: 'APPLY',      status: 'locked',   time: null,    note: 'UNLOCKS AFTER PHASE 2' },
];

export const BLOOM_STAGES: BloomStage[] = [
  { label: 'Remember',                   state: 'done',   note: 'Terms, glossary, practices'   },
  { label: 'Understand',                 state: 'active', note: 'Signals, lifecycle, why'       },
  { label: 'Apply',                      state: 'next',   note: 'Sim · controlled scenarios'    },
  { label: 'Analyse · Evaluate · Create', state: 'locked', note: 'Unlocks post-track'           },
];
