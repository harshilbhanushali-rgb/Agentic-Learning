import type { Spotlight, CourseSectionData, CaseStudy, FailureEntry } from "@/types";
/* Library mock data + helpers — extracted from library/page.js */

export const SPOTLIGHT: Spotlight = {
  veteran: {
    id: 1,
    title: 'The CFO Objection Playbook',
    desc: 'Six proven frameworks for navigating finance-led pushback on renewal and expansion deals — from timeline deflection to ROI ambiguity.',
    tags: ['Negotiation', 'Executive', 'Renewal'],
    modules: 8,
    readTime: '42 min',
  },
  newbie: {
    id: 2,
    title: 'Discovery Fundamentals',
    desc: 'Build the habit of asking before telling. This module covers the five discovery questions every Champion needs before any demo or proposal.',
    tags: ['Discovery', 'Foundations'],
    modules: 5,
    readTime: '28 min',
  },
};

export const COURSE_SECTIONS: CourseSectionData[] = [
  {
    title: 'Negotiation',
    courses: [
      { id: 101, title: 'Anchoring in Renewal Conversations', desc: 'Set the right reference point before pricing enters the room.', tags: ['Negotiation', 'Renewal'] },
      { id: 102, title: 'The Value Triangle', desc: 'Frame ROI, risk, and timing as a single coherent story.', tags: ['Negotiation', 'Storytelling'] },
      { id: 103, title: 'Silence as Strategy', desc: 'When to stop talking — and what it signals to the other side.', tags: ['Negotiation'] },
      { id: 104, title: 'Multi-Stakeholder Alignment', desc: 'Getting procurement, finance, and the Champion to move together.', tags: ['Negotiation', 'Executive'] },
      { id: 105, title: 'Price Objection Anatomy', desc: 'Classify price objections before responding to them.', tags: ['Negotiation', 'Objections'] },
      { id: 106, title: 'Concession Mapping', desc: 'Know which concessions cost you nothing but mean everything to them.', tags: ['Negotiation'] },
    ],
  },
  {
    title: 'Discovery',
    courses: [
      { id: 201, title: 'The 5 Before the Demo', desc: 'Five questions to ask before any product walkthrough — every time.', tags: ['Discovery', 'Foundations'] },
      { id: 202, title: 'Mapping the Decision Circle', desc: 'Identify every stakeholder who can say yes — and everyone who can say no.', tags: ['Discovery'] },
      { id: 203, title: 'Pain vs. Symptom', desc: 'Distinguish the real problem from the presenting complaint.', tags: ['Discovery', 'Diagnosis'] },
      { id: 204, title: 'Reading Between the Lines', desc: 'What clients mean when they say "just send me a proposal."', tags: ['Discovery', 'Reading Signals'] },
      { id: 205, title: 'Timeline Interrogation', desc: "Uncover the real urgency — and what's really driving it.", tags: ['Discovery'] },
      { id: 206, title: 'The Quiet Stakeholder', desc: "Drawing out the person who hasn't spoken in the room.", tags: ['Discovery', 'Stakeholders'] },
    ],
  },
  {
    title: 'Objection Handling',
    courses: [
      { id: 301, title: 'The Four Objection Types', desc: 'Classify before you respond — not every objection is what it sounds like.', tags: ['Objections', 'Frameworks'] },
      { id: 302, title: 'Competitor Deflection', desc: "How to handle \"we're also looking at X\" without bad-mouthing or panicking.", tags: ['Objections', 'Competition'] },
      { id: 303, title: 'The "Send Me More Info" Trap', desc: 'Recognize stall tactics and respond without pressure.', tags: ['Objections', 'Reading Signals'] },
      { id: 304, title: 'Legal and Security Objections', desc: 'Navigate InfoSec and legal review without derailing momentum.', tags: ['Objections', 'Process'] },
      { id: 305, title: 'Champion Goes Cold', desc: 'What to do when your internal advocate stops responding.', tags: ['Objections', 'Relationships'] },
      { id: 306, title: 'Reframing the Status Quo', desc: 'The cost of doing nothing is still a cost — make it visible.', tags: ['Objections', 'Storytelling'] },
    ],
  },
];

export const CASE_STUDIES: CaseStudy[] = [
  {
    id: 1,
    account: 'Account J',
    headline: 'The renewal that almost slipped — a new chapter just dropped.',
    sector: 'SaaS',
    region: 'NA',
    monthsActive: 18,
    total: 6,
    status: 'live',
    justDropped: true,
    participants: 7,
    context: 'Enterprise SaaS · $420K ARR · Renewal',
    chapters: [
      { num: 1, title: 'The QBR That Almost Missed', summary: "How leading with client KPIs instead of product metrics changed the room's energy in the first 10 minutes." },
      { num: 2, title: 'The Competitor Mention', summary: 'A mid-call reference to a rival platform — and the silence that followed — handled in real time.' },
      { num: 3, title: 'Closing the Loop', summary: 'Getting a verbal yes from a CFO who had been non-committal for 45 minutes.' },
    ],
  },
  {
    id: 2,
    account: 'Account F',
    headline: 'A discovery miss, and the recovery that saved the expansion.',
    sector: 'Mid-Market',
    region: 'EMEA',
    monthsActive: 11,
    total: 4,
    status: 'live',
    justDropped: false,
    participants: 4,
    context: 'Mid-Market · $180K ARR · Expansion',
    chapters: [
      { num: 1, title: 'Discovery Breakdown', summary: 'What the CSM missed in the discovery call that created a mismatch at the proposal stage.' },
      { num: 2, title: 'Recovering the Narrative', summary: 'Reframing the value proposition after the client expressed disappointment with onboarding speed.' },
    ],
  },
  {
    id: 3,
    account: 'Account R',
    headline: 'Churn signals in the data, caught just in time.',
    sector: 'Enterprise',
    region: 'APAC',
    monthsActive: 24,
    total: 3,
    status: 'historical',
    justDropped: false,
    participants: 12,
    context: 'Enterprise · $620K ARR · Churn Risk Averted',
    chapters: [
      { num: 1, title: 'Reading the Signals', summary: 'Three months of declining engagement that were visible in the data — and missed in the QBR.' },
      { num: 2, title: 'The Intervention Call', summary: 'A 90-minute call that changed the trajectory: what was said and what was left unsaid.' },
      { num: 3, title: 'The Recovery Plan', summary: 'A six-week joint success plan that rebuilt trust and created a reference customer.' },
    ],
  },
  {
    id: 4,
    account: 'Account M',
    headline: 'Small ARR, big lesson — timing the upsell to outcomes.',
    sector: 'SMB',
    region: 'NA',
    monthsActive: 9,
    total: 3,
    status: 'historical',
    justDropped: false,
    participants: 3,
    context: 'SMB · $62K ARR · Upsell',
    chapters: [
      { num: 1, title: 'The Small Account Trap', summary: "Why small ARR doesn't mean low complexity — and how this account taught a senior CSM a lesson." },
      { num: 2, title: 'The Right Ask', summary: 'Timing an upsell conversation to business outcomes, not contract renewal dates.' },
    ],
  },
  {
    id: 5,
    account: 'Account T',
    headline: 'Sponsor gone, relationship rebuilt from zero.',
    sector: 'Enterprise',
    region: 'EMEA',
    monthsActive: 31,
    total: 5,
    status: 'live',
    justDropped: true,
    participants: 9,
    context: 'Enterprise · $890K ARR · Strategic Review',
    chapters: [
      { num: 1, title: 'The Executive Sponsor Problem', summary: 'When your champion gets promoted and their replacement has different priorities entirely.' },
      { num: 2, title: 'Rebuilding the Relationship', summary: 'How to re-establish value with a new buyer who did not select you.' },
      { num: 3, title: 'From Vendor to Partner', summary: 'The shift in language and behavior that changed how the account perceived Joveo.' },
    ],
  },
];

/* Deterministic bar heights (SSR-safe — no Math.random / Date) */
export function csBars(seed: string, n = 30): number[] {
  let x = 0;
  for (let i = 0; i < seed.length; i++) x = (x * 31 + seed.charCodeAt(i)) % 9973;
  const out = [];
  for (let i = 0; i < n; i++) {
    x = (x * 1103515245 + 12345) & 0x7fffffff;
    out.push(26 + (x % 70)); // 26–96%
  }
  return out;
}

export const FAILURE_LIBRARY: FailureEntry[] = [
  {
    id: 1,
    deal: 'Novo Nordisk',
    category: 'Pricing',
    lesson: 'Ranges signal uncertainty. When asked about ROI timeline, we gave a range instead of a committed number — and the CFO pushed back for three weeks.',
    quarter: 'Q3 2024',
    fullPostMortem: "The deal had been tracking well for six months. In the final commercial call, the CFO asked for a concrete ROI projection. Instead of committing to a number with appropriate caveats, the CSM offered a range. The CFO interpreted this as uncertainty about product value. The conversation stalled for three weeks before a competitor with a confident projection closed the deal. Lesson: commit to a number, explain your assumptions, and invite pushback on the assumptions — not on whether you believe in your own product.",
  },
  {
    id: 2,
    deal: 'Carrefour APAC',
    category: 'Champion Loss',
    lesson: 'We had one champion and no backup. When she moved to a competitor, the deal evaporated within 60 days.',
    quarter: 'Q1 2024',
    fullPostMortem: "The Carrefour APAC relationship was built entirely around a single Director of Talent Acquisition. When she left for a competitor, the new head of TA had no context on the partnership and no relationship with the team. By April, the account had signed with a local provider at a lower price point. Any account over $200K ARR should have at least two named champions at different levels and functions.",
  },
  {
    id: 3,
    deal: 'Siemens Energy',
    category: 'Timing',
    lesson: "We pushed for a Q4 close on the client's Q1 fiscal year. The deal slipped into a budget cycle we couldn't control.",
    quarter: 'Q4 2023',
    fullPostMortem: "Siemens Energy operates on a January fiscal year. Our team was pushing for a December close to hit internal targets. The client was willing in principle but not ready to commit capital in Q4 of their fiscal year. The deal ultimately closed in February at the same price — but we lost three months and created friction with a client who went on to be a strong reference. Push for client timing, not internal quota timing.",
  },
  {
    id: 4,
    deal: 'Unilever NA',
    category: 'Product Fit',
    lesson: 'We oversold the integration depth in discovery. When engineering scoped it, the gap was too large to close.',
    quarter: 'Q2 2024',
    fullPostMortem: "During discovery, the CSM described the Workday integration as native and bidirectional. In practice, it required a custom middleware layer that engineering estimated at 120 hours. When that estimate landed on the client's desk, the deal went into security and legal review as a custom software project. It never recovered. Never describe integrations as native without checking with engineering first.",
  },
  {
    id: 5,
    deal: 'BNP Paribas',
    category: 'Legal / Compliance',
    lesson: "We didn't surface the data residency requirement until week 8 of a 10-week deal. The deal reset to week 1.",
    quarter: 'Q1 2025',
    fullPostMortem: "BNP Paribas requires all talent data to reside within EU jurisdiction. This was mentioned once in an early email and not captured in the deal notes. Eight weeks into a complex procurement process, legal sent a data processing agreement that revealed the requirement. Our infrastructure at the time did not support EU-only residency. The deal reset to a technical evaluation phase. Ask about data residency requirements in the first discovery call — every time, for every financial services client.",
  },
  {
    id: 6,
    deal: 'Foxconn Industrial',
    category: 'Internal Misalignment',
    lesson: 'Sales promised a go-live in 6 weeks. Implementation scoped it at 16 weeks. The client found out from implementation, not from us.',
    quarter: 'Q3 2023',
    fullPostMortem: "The sales handoff to customer success happened without a scope call. The AE had promised a 6-week implementation timeline based on a similar but structurally different customer. When the CSM ran the kickoff and scoped the actual configuration requirements, the timeline came out at 16 weeks. The client's CHRO found out in the kickoff call, in front of their team. The relationship never fully recovered. Every handoff requires a scope call with implementation before any timeline is communicated to the client.",
  },
  {
    id: 7,
    deal: 'Deutsche Telekom',
    category: 'Stakeholder Management',
    lesson: 'We built the entire renewal narrative for the IT sponsor — not the business buyer. The business buyer killed it.',
    quarter: 'Q2 2023',
    fullPostMortem: "The Deutsche Telekom renewal was tracked through the IT sponsor who had championed the technical onboarding. For twelve months, all QBR decks and ROI reports were built for an IT audience. The actual renewal decision was made by the Chief People Officer, who had never received business-outcome-oriented communication. When she asked what business problem this solves, no one in the room could answer. The deal renewed at a 30% discount. Know who owns the renewal budget — and speak their language.",
  },
];
