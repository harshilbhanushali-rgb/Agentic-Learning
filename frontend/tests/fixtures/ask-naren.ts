import type {
  AskNarenAnswer,
  AskNarenCitation,
  AskNarenClarify,
  AskNarenDecline,
  AskNarenDeclineReason,
  AskNarenExchange,
  AskNarenMatch,
  AskNarenRendered,
} from '@/types';

/**
 * Response fixtures for the Ask Naren render paths.
 *
 * TWO PER RENDERED KIND, deliberately: a "maximal" one where every optional field is
 * present and every count is plural, and a "minimal" one where they are absent and
 * singular. Nearly all the branching in RenderedAnswer.tsx is a ternary choosing copy
 * ("1 call" vs "3 calls", "the whole play" vs "getting better at this"), so a single
 * fixture per kind would render green while taking exactly one side of every one of them.
 */

export function citation(over: Partial<AskNarenCitation> = {}): AskNarenCitation {
  return {
    label: 'Account A · March 2024',
    call_filename: 'call_001.json',
    pair_id: 42,
    scenario_key: 'performance_pushback',
    ...over,
  };
}

export function match(over: Partial<AskNarenMatch> = {}): AskNarenMatch {
  return { cosine: 0.71, scenario_key: 'performance_pushback', rank: 1, ...over };
}

export function exchange(over: Partial<AskNarenExchange> = {}): AskNarenExchange {
  return {
    client_said: 'Applications have been flat for three weeks.',
    naren_replied: 'Let us look at delivery before we touch the budget.',
    ...over,
  };
}

export function answer(over: Partial<AskNarenAnswer> = {}): AskNarenAnswer {
  return {
    outcome: 'answered',
    answer: 'Open with the delivery number rather than an apology.',
    quote: 'Let us look at delivery before we touch the budget.',
    citation: citation(),
    match: match(),
    ...over,
  } as AskNarenAnswer;
}

export function decline(
  reason: AskNarenDeclineReason,
  over: Partial<AskNarenDecline> = {},
): AskNarenDecline {
  return {
    outcome: 'declined',
    reason,
    message: `A CSM-safe sentence explaining ${reason}.`,
    ...over,
  };
}

export function clarify(over: Partial<AskNarenClarify> = {}): AskNarenClarify {
  return {
    outcome: 'clarify',
    question: 'Which account, and what did they actually say?',
    ...over,
  };
}

const SCENARIOS = [
  { scenario_key: 'performance_pushback', description: 'The client says results are flat.' },
  { scenario_key: 'budget_pressure', description: 'The client wants to cut spend.' },
];

/** Every rendered kind, at its richest: optionals present, counts plural. */
export const maximal: Record<AskNarenRendered['kind'], AskNarenRendered> = {
  discovery: {
    outcome: 'rendered',
    kind: 'discovery',
    grouped: true,
    topics: [{ topic: 'Delivery', scenarios: SCENARIOS }],
    scenarios: SCENARIOS,
    total: 34,
  },
  frequency: {
    outcome: 'rendered',
    kind: 'frequency',
    scenarios: SCENARIOS.map(s => ({ ...s, support_calls: 9, call_coverage: 0.3 })),
    total: 34,
    basis: 'Ranked across Naren’s recorded calls, not across clients generally.',
  },
  show_exchange: {
    outcome: 'rendered',
    kind: 'show_exchange',
    exchange: exchange(),
    citation: citation(),
    match: match(),
  },
  what_happened_next: {
    outcome: 'rendered',
    kind: 'what_happened_next',
    match: match(),
    exchange: exchange(),
    following: [{ ...exchange({ client_said: 'And the CPA?' }), scenario_key: 'budget_pressure' }],
    is_last: false,
    citation: citation(),
  },
  coverage_check: {
    outcome: 'rendered',
    kind: 'coverage_check',
    asked_about: 'a stalled ramp',
    nearest: { ...SCENARIOS[0], support_calls: 9, evidence: 'solid' },
    citation: citation(),
    match: match(),
  },
  sequence: {
    outcome: 'rendered',
    kind: 'sequence',
    match: match(),
    scenario_key: 'performance_pushback',
    steps: ['Check delivery.', 'Show the number.', 'Agree one change.'],
  },
  phrasing: {
    outcome: 'rendered',
    kind: 'phrasing',
    match: match(),
    scenario_key: 'performance_pushback',
    phrases: [
      {
        phrase: 'Let us look at delivery first',
        quote: 'Before we touch budget, let us look at delivery.',
        call: 'call_001.json',
        label: 'Account A · March 2024',
      },
    ],
  },
  pitfalls: {
    outcome: 'rendered',
    kind: 'pitfalls',
    match: match(),
    scenario_key: 'performance_pushback',
    pitfalls: [
      {
        text: 'Promising a number before checking delivery.',
        evidence: [
          { quote: 'I will not give you a figure today.', call: 'call_002.json', label: 'Account B' },
        ],
      },
    ],
  },
  scenario_check: {
    outcome: 'rendered',
    kind: 'scenario_check',
    match: match(),
    asked_about: 'flat applies',
    scenario_key: 'performance_pushback',
    applies_when: 'The client has raised results and spend is already live.',
  },
  play_confidence: {
    outcome: 'rendered',
    kind: 'play_confidence',
    match: match(),
    scenario_key: 'performance_pushback',
    moves: 4,
    quotes: 9,
    n_evidence: 50,
    n_evidence_capped: true,
    basis: 'Counted from the live playbook document.',
  },
  where_else_seen: {
    outcome: 'rendered',
    kind: 'where_else_seen',
    asked_about: 'flat applies',
    scenario_key: 'performance_pushback',
    same_scenario: 6,
    accounts: [
      { account: 'Account A', named: true, exchanges: 4, calls: 2 },
      { account: '8f2c19ae-5b31.json', named: false, exchanges: 1, calls: 1 },
    ],
    accounts_named: 1,
    accounts_at_least: 2,
    accounts_at_most: 3,
    unnamed_calls: 1,
    exchanges: 20,
    basis: 'Scanned the 25 nearest exchanges.',
  },
  call_prep: {
    outcome: 'rendered',
    kind: 'call_prep',
    asked_about: 'a renewal call',
    scenarios: [
      {
        ...SCENARIOS[0],
        exchanges: 15,
        has_play: true,
        steps: ['Check delivery.', 'Show the number.'],
        example: { ...exchange(), citation: citation() },
      },
    ],
    scenarios_found: 7,
    exchanges: 20,
    basis: 'Assembled from what is on file.',
  },
  improve_at_move: {
    outcome: 'rendered',
    kind: 'improve_at_move',
    match: match(),
    asked_about: 'opening the call',
    scenario_key: 'performance_pushback',
    focused: true,
    moves: [
      {
        name: 'Open on delivery',
        criterion: 'States the delivery number before any apology.',
        evidence: [
          { quote: 'Before we touch budget, let us look at delivery.', call: 'call_001.json', label: 'Account A' },
        ],
      },
    ],
    pitfalls: [
      {
        text: 'Leading with an apology.',
        evidence: [{ quote: 'Sorry about the numbers.', call: 'call_003.json', label: 'Account C' }],
      },
    ],
    basis: 'Built from the live playbook.',
  },
};

/** The same kinds with every optional absent, every count singular, every flag flipped. */
export const minimal: Record<AskNarenRendered['kind'], AskNarenRendered> = {
  discovery: {
    ...maximal.discovery,
    grouped: false,
    topics: [],
    // an empty description exercises the ScenarioLine branch that omits it
    scenarios: [{ scenario_key: 'performance_pushback', description: '' }],
    total: 1,
  } as AskNarenRendered,
  frequency: {
    ...maximal.frequency,
    scenarios: [
      { scenario_key: 'performance_pushback', description: '', support_calls: 1, call_coverage: null },
    ],
  } as AskNarenRendered,
  show_exchange: maximal.show_exchange,
  what_happened_next: {
    ...maximal.what_happened_next,
    following: [],
    is_last: true,
  } as AskNarenRendered,
  coverage_check: {
    ...maximal.coverage_check,
    nearest: {
      scenario_key: 'performance_pushback',
      description: '',
      support_calls: 1,
      evidence: 'thin',
    },
  } as AskNarenRendered,
  sequence: maximal.sequence,
  phrasing: maximal.phrasing,
  pitfalls: maximal.pitfalls,
  scenario_check: maximal.scenario_check,
  play_confidence: {
    ...maximal.play_confidence,
    moves: 1,
    quotes: 1,
    n_evidence: 16,
    n_evidence_capped: false,
  } as AskNarenRendered,
  where_else_seen: {
    ...maximal.where_else_seen,
    same_scenario: 1,
    exchanges: 1,
    accounts: [{ account: 'Account A', named: true, exchanges: 1, calls: 1 }],
    accounts_at_least: 1,
    accounts_at_most: 1,
  } as AskNarenRendered,
  call_prep: {
    ...maximal.call_prep,
    scenarios: [
      {
        scenario_key: 'performance_pushback',
        description: '',
        exchanges: 1,
        has_play: false,
        steps: [],
        example: { ...exchange(), citation: citation() },
      },
    ],
    // equal to scenarios.length, so the "trimmed list" clause must not render
    scenarios_found: 1,
  } as AskNarenRendered,
  improve_at_move: {
    ...maximal.improve_at_move,
    focused: false,
    moves: [{ name: 'Open on delivery', criterion: '', evidence: [] }],
    pitfalls: [],
  } as AskNarenRendered,
};

export const RENDERED_KINDS = Object.keys(maximal) as AskNarenRendered['kind'][];
