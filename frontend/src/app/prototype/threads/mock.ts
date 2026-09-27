/**
 * PROTOTYPE MOCK DATA (issue #39) — throwaway, never imported by real code.
 *
 * Questions are drawn from the situations the corpus covers well (onboarding: ATS, XML feeds,
 * contracts, landing pages, dashboards, budget tests) — see
 * ask-naren/docs/findings/corpus-is-onboarding-not-escalation.md. The one escalation question
 * (pausing spend mid-quarter) declines, as it does on the live service.
 *
 * Client names, call filenames and quotes are invented.
 */
import type { AskNarenResponse } from '@/types';

export interface MockTurn {
  message: string;
  response: AskNarenResponse;
  askedAt: string;
}

export interface MockThread {
  id: string;
  /** Set only once a CSM renames it; otherwise the title is derived from turn 1. */
  customTitle?: string;
  turns: MockTurn[];
}

/** Fixed "now" so server and client render the same relative dates. */
export const NOW = new Date('2026-09-28T15:00:00Z').getTime();

const ats = {
  label: '2026-03-11_Naren_x_Northwind-Health_ATS-kickoff.txt',
  call_filename: '2026-03-11_Naren_x_Northwind-Health_ATS-kickoff.txt',
  pair_id: 48213,
  scenario_key: 'ats_integration_and_api_mapping',
};

export const THREADS: MockThread[] = [
  {
    id: 't1',
    turns: [
      {
        askedAt: '2026-09-28T12:40:00Z',
        message:
          'On today’s kickoff their TA lead said: “How long does the ATS integration take on our side? Our IT team is booked solid through March.” How would Naren answer that?',
        response: {
          outcome: 'answered',
          answer:
            'Naren shrinks the ask before he answers it. He tells them their side is a couple of hours from whoever owns the ATS — generating API credentials and approving one test apply — and that the mapping work sits with Joveo.\n\nThen he pins the one date that matters: when those credentials arrive. He does not promise a go-live until he has it.',
          quote:
            'honestly on your side it’s a couple of hours from whoever owns Workday — they generate the credentials, we do the mapping, and then we just need somebody to sanity-check one test apply',
          citation: ats,
          match: { cosine: 0.83, scenario_key: 'ats_integration_and_api_mapping', rank: 1 },
        },
      },
      {
        askedAt: '2026-09-28T12:44:00Z',
        message: 'And if they push back that even a couple of hours is hard to get out of IT?',
        response: {
          outcome: 'answered',
          answer:
            'He offers to get on a 20-minute call with their IT contact directly, so the TA lead is not the one translating. He frames it as taking work off IT, not adding to it.',
          quote:
            'if it helps, put me on a twenty-minute call with your IT person and I’ll walk them through it, so it’s not on you to relay it',
          citation: ats,
        },
      },
      {
        askedAt: '2026-09-28T12:51:00Z',
        message:
          'Different thing — they also said they might pause spend halfway through Q2 if hiring slows. What’s the play there?',
        response: {
          outcome: 'declined',
          reason: 'no_close_match',
          message:
            'Nothing in Naren’s calls is close enough to this to ground an answer on. The nearest exchanges are about agreeing an initial budget, not pausing a running one.',
        },
      },
    ],
  },
  {
    id: 't2',
    turns: [
      {
        askedAt: '2026-09-27T09:10:00Z',
        message:
          'Client is moving their XML feed over from their current vendor. What do they actually need to send us, and in what format?',
        response: {
          outcome: 'answered',
          answer:
            'Naren asks for the feed URL they already publish to the old vendor before asking for anything new — most of the time it can be ingested as-is, and the gaps are a couple of fields.',
          quote:
            'send me the URL you give them today — nine times out of ten we can take that as it is and just tell you the two fields we’re missing',
          citation: {
            label: '2026-05-02_Naren_x_Ridgeway-Logistics_feed-migration.txt',
            call_filename: '2026-05-02_Naren_x_Ridgeway-Logistics_feed-migration.txt',
            pair_id: 51102,
            scenario_key: 'xml_feed_setup_and_ingestion',
          },
        },
      },
      {
        askedAt: '2026-09-27T09:14:00Z',
        message: 'What if the old vendor won’t give them the URL?',
        response: {
          outcome: 'declined',
          reason: 'follow_up_ungrounded',
          message: 'Naren did not cover that in the call the previous answer came from.',
        },
      },
    ],
  },
  {
    id: 't3',
    turns: [
      {
        askedAt: '2026-09-25T16:30:00Z',
        message:
          'Client said: “Legal is redlining the MSA over the data-processing clause and it’ll take weeks.” How did Naren keep it moving?',
        response: {
          outcome: 'answered',
          answer:
            'He separates the contract from the build: he offers to start feed and ATS setup in parallel under the existing NDA so the redline is not on the critical path.',
          quote:
            'let legal do their thing, that’s fine — there’s nothing stopping us getting your feed and the integration built in the meantime',
          citation: {
            label: '2026-01-19_Naren_x_Harbor-Retail_contract.txt',
            call_filename: '2026-01-19_Naren_x_Harbor-Retail_contract.txt',
            pair_id: 40551,
            scenario_key: 'contract_and_legal_review',
          },
        },
      },
    ],
  },
  {
    id: 't4',
    customTitle: 'Northwind — landing page conversion',
    turns: [
      {
        askedAt: '2026-09-22T11:05:00Z',
        message:
          'Client said: “Why does our landing page convert worse than the job board’s own apply flow?”',
        response: {
          outcome: 'answered',
          answer:
            'Naren asks how many screens stand between the click and the first question on the form before discussing anything else, and offers to review the flow live on the call.',
          quote: 'can you share your screen and just click through it as if you were a candidate',
          citation: {
            label: '2026-06-08_Naren_x_Northwind-Health_landing-review.txt',
            call_filename: '2026-06-08_Naren_x_Northwind-Health_landing-review.txt',
            pair_id: 55320,
            scenario_key: 'landing_page_and_conversion_setup',
          },
        },
      },
    ],
  },
  {
    id: 't5',
    turns: [
      {
        askedAt: '2026-09-16T14:20:00Z',
        message:
          'Client said their agency needs dashboard access too. I replied: “We can only give logins to your own team.” How does that compare to what Naren did?',
        response: {
          outcome: 'answered',
          my_reply: 'We can only give logins to your own team.',
          answer:
            'You declined the access outright. Naren asked what the agency needs to see, then offered a read-only view scoped to the campaigns they run.',
          quote: 'what does the agency actually need to look at — is it spend, or is it applies',
          citation: {
            label: '2026-04-14_Naren_x_Crestline-Energy_reporting.txt',
            call_filename: '2026-04-14_Naren_x_Crestline-Energy_reporting.txt',
            pair_id: 49877,
            scenario_key: 'dashboard_access_and_reporting',
          },
        },
      },
    ],
  },
  {
    id: 't6',
    turns: [
      {
        askedAt: '2026-09-04T10:00:00Z',
        message:
          'Client wants to split the first month’s budget across three test markets before committing. How did Naren set that up?',
        response: {
          outcome: 'answered',
          answer:
            'He agrees to the test but insists on one success number per market, written down before launch, so the review in week four is a comparison rather than a debate.',
          quote: 'before we switch anything on, let’s write down what good looks like in each city',
          citation: {
            label: '2026-02-26_Naren_x_Pinecrest-Care_budget-test.txt',
            call_filename: '2026-02-26_Naren_x_Pinecrest-Care_budget-test.txt',
            pair_id: 44109,
            scenario_key: 'budget_allocation_and_testing',
          },
        },
      },
    ],
  },
];

/** Title from the first message: first ~60 characters, cut at a word. */
export function deriveTitle(t: MockThread): string {
  if (t.customTitle) return t.customTitle;
  const first = t.turns[0]?.message ?? '';
  if (first.length <= 60) return first;
  const cut = first.slice(0, 60);
  return cut.slice(0, cut.lastIndexOf(' ')) + '…';
}

export function lastAskedAt(t: MockThread): number {
  return new Date(t.turns[t.turns.length - 1].askedAt).getTime();
}

export function relative(ts: number): string {
  const mins = Math.round((NOW - ts) / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days <= 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;
  return new Date(ts).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

export function bucket(ts: number): string {
  const days = (NOW - ts) / 86400000;
  if (days < 1) return 'Today';
  if (days < 2) return 'Yesterday';
  if (days < 7) return 'This week';
  if (days < 30) return 'This month';
  return 'Older';
}

/** The situation of the first answered turn — possible only because stored turns keep it. */
export function firstSituation(t: MockThread): string | null {
  for (const turn of t.turns) {
    if (turn.response.outcome === 'answered') return turn.response.citation.scenario_key;
  }
  return null;
}
