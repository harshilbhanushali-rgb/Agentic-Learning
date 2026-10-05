import { describe, it, expect, vi } from 'vitest';
import {
  carriedScenario,
  clearLegacyThreads,
  scenarioLabel,
  summaryJson,
  threadJson,
  trimThread,
  turnFrom,
  type ThreadTurn,
} from './thread';
import type { AskNarenResponse } from '@/types';
import { citation, maximal } from '../../tests/fixtures/ask-naren';

/** The retired browser-held thread's key prefix; see `clearLegacyThreads`. */
const STORAGE_KEY = 'cs-ask-naren-thread-v1';

function turn(over: Partial<ThreadTurn> = {}): ThreadTurn {
  return {
    message: 'client says applies are flat',
    outcome: 'answered',
    reply: 'Show them the delivery number first.',
    scenario_key: 'performance_pushback',
    pair_id: 42,
    call_filename: 'call_001.json',
    ...over,
  };
}

describe('turnFrom', () => {
  it('keeps the citation identifiers off an answered response', () => {
    const result = {
      outcome: 'answered',
      answer: 'Lead with delivery.',
      citation: {
        label: 'Account A',
        call_filename: 'call_009.json',
        pair_id: 7,
        scenario_key: 'performance_pushback',
      },
    } as unknown as AskNarenResponse;

    expect(turnFrom('why flat?', result)).toEqual({
      message: 'why flat?',
      outcome: 'answered',
      reply: 'Lead with delivery.',
      scenario_key: 'performance_pushback',
      pair_id: 7,
      call_filename: 'call_009.json',
    });
  });

  it('carries a null pair_id for a Layer C answer that cites no kb_pairs row', () => {
    const result = {
      outcome: 'answered',
      answer: 'Ask what changed upstream.',
      citation: { label: 'A', call_filename: 'c.json', scenario_key: 'ramp' },
    } as unknown as AskNarenResponse;

    // Deliberate: a follow-up with no pair_id is answered fresh rather than grounded in
    // whatever happened to be cited earlier.
    expect(turnFrom('q', result).pair_id).toBeNull();
  });

  it('records a clarify question verbatim and grounds nothing', () => {
    const result = { outcome: 'clarify', question: 'Which account?' } as unknown as AskNarenResponse;
    expect(turnFrom('help', result)).toMatchObject({
      outcome: 'clarify',
      reply: 'Which account?',
      scenario_key: '',
      pair_id: null,
      call_filename: '',
    });
  });

  it('records a decline message and grounds nothing', () => {
    const result = {
      outcome: 'declined',
      reason: 'no_close_match',
      message: 'Nothing close enough.',
    } as unknown as AskNarenResponse;
    expect(turnFrom('q', result)).toMatchObject({
      outcome: 'declined',
      reply: 'Nothing close enough.',
      pair_id: null,
    });
  });

  it('summarises a rendered answer by kind', () => {
    expect(turnFrom('show me', maximal.show_exchange)).toMatchObject({
      outcome: 'rendered',
      reply: 'Showed the real exchange.',
    });
  });

  /* What a rendered turn records is what the NEXT message can carry (issue #52, ADR 0013):
   * after "what's the play for X", "and how does he word it?" continues from X only if this
   * turn says X. Each kind records exactly the identifiers its response already holds. */
  it.each(['sequence', 'phrasing', 'pitfalls', 'scenario_check', 'play_confidence', 'improve_at_move'] as const)(
    'a %s turn records the scenario its play was for, and no exchange',
    kind => {
      const result = { ...maximal[kind], scenario_key: 'budget_pressure' } as AskNarenResponse;
      expect(turnFrom('q', result)).toMatchObject({ scenario_key: 'budget_pressure', pair_id: null });
    },
  );

  it('a coverage_check turn records the nearest scenario, and no exchange', () => {
    const result = {
      ...maximal.coverage_check,
      nearest: { scenario_key: 'budget_pressure', description: '', support_calls: 3, evidence: 'thin' },
      citation: citation({ scenario_key: 'budget_pressure', pair_id: 9 }),
    } as AskNarenResponse;
    expect(turnFrom('q', result)).toMatchObject({ scenario_key: 'budget_pressure', pair_id: null });
  });

  it.each(['show_exchange', 'what_happened_next'] as const)(
    'a %s turn records the exchange it showed, from its citation',
    kind => {
      const result = {
        ...maximal[kind],
        citation: citation({ scenario_key: 'budget_pressure', pair_id: 9 }),
      } as AskNarenResponse;
      expect(turnFrom('q', result)).toMatchObject({ scenario_key: 'budget_pressure', pair_id: 9 });
    },
  );

  it.each(['discovery', 'frequency', 'where_else_seen', 'call_prep'] as const)(
    'a %s turn records nothing: it is about many situations, not one',
    kind => {
      expect(turnFrom('q', maximal[kind])).toMatchObject({ scenario_key: '', pair_id: null, call_filename: '' });
    },
  );

  it('a rendered turn records no call filename, so the thread shown to intake is unchanged', () => {
    // `threads.render` prints "(grounded in <call>)" for a turn with a call filename. A
    // rendered answer grounded nothing, and adding that line would change the intake prompt.
    expect(turnFrom('q', maximal.show_exchange).call_filename).toBe('');
  });

  it('throws on an outcome outside the union rather than inventing a turn', () => {
    const result = { outcome: 'something_new' } as unknown as AskNarenResponse;
    expect(() => turnFrom('q', result)).toThrow(/unhandled outcome/);
  });
});

describe('trimThread', () => {
  it('returns an empty thread untouched', () => {
    expect(trimThread([])).toEqual([]);
  });

  it('leaves a thread that already fits alone', () => {
    const turns = [turn(), turn()];
    expect(trimThread(turns, 64 * 1024)).toEqual(turns);
  });

  it('elides the middle first, oldest first, keeping every identifier', () => {
    const turns = [
      turn({ message: 'first '.repeat(200) }),
      turn({ message: 'second '.repeat(200) }),
      turn({ message: 'third '.repeat(200) }),
      turn({ message: 'fourth '.repeat(200) }),
      turn({ message: 'fifth '.repeat(200) }),
    ];
    const out = trimThread(turns, 6000);

    // Whatever prose was dropped, every identifier survived -- that is the rule ADR 0006
    // sets, and the reason the unit of trimming is a turn's text rather than the turn.
    expect(out).toHaveLength(5);
    for (const t of out) {
      expect(t.scenario_key).toBe('performance_pushback');
      expect(t.pair_id).toBe(42);
      expect(t.call_filename).toBe('call_001.json');
    }
    // The middle went before the first did.
    expect(out[1].message).toBe('');
    expect(out[0].message).not.toBe('');
  });

  it('elides the first turn once eliding the middle is not enough', () => {
    const turns = [
      turn({ message: 'x'.repeat(4000) }),
      turn({ message: 'y'.repeat(4000) }),
      turn({ message: 'z'.repeat(200) }),
    ];
    const out = trimThread(turns, 2000);
    expect(out[0].message).toBe('');
  });

  /* NOTE these two use a two-turn thread deliberately. On a single-turn thread index 0 IS
   * the last turn, so the earlier `elide(0)` clears both fields and the last-turn rules
   * below are never reached. The distinction only exists once there is an older turn to
   * sacrifice first. */
  it('drops the last turn reply before its message', () => {
    const older = turn({ message: 'x'.repeat(2000), reply: 'y'.repeat(2000) });
    const last = turn({ message: 'a'.repeat(3000), reply: 'b'.repeat(3000) });

    // Budget derived, not guessed: exactly the size the thread reaches once the older turn
    // is elided and the last reply dropped. At that budget the last message must survive
    // whole -- it is what a follow-up refers to, so its prose goes last.
    const budget = new Blob([
      JSON.stringify([{ ...older, message: '', reply: '' }, { ...last, reply: '' }]),
    ]).size;

    const out = trimThread([older, last], budget);
    expect(out[0].message).toBe('');
    expect(out[1].reply).toBe('');
    expect(out[1].message).toBe(last.message);
  });

  it('truncates the last message when even that is too big', () => {
    const older = turn({ message: 'x'.repeat(2000), reply: 'y'.repeat(2000) });
    const last = turn({ message: 'a'.repeat(8000), reply: 'b'.repeat(8000) });

    const out = trimThread([older, last], 1200);
    expect(out[1].reply).toBe('');
    expect(out[1].message.length).toBeLessThan(8000);
    // Identifiers are never what gets cut.
    expect(out[1].pair_id).toBe(42);
  });

  it('finally sheds the oldest turns when identifiers alone will not fit', () => {
    const turns = Array.from({ length: 60 }, (_, i) => turn({ message: 'm' + i, reply: 'r' + i }));
    const out = trimThread(turns, 400);
    expect(out.length).toBeLessThan(60);
    expect(out.length).toBeGreaterThanOrEqual(1);
    // The newest carried identifier is the live one, so the tail is what survives.
    expect(out[out.length - 1].pair_id).toBe(42);
  });
});

describe('scenarioLabel', () => {
  it('reads a scenario key as prose', () => {
    expect(scenarioLabel('performance_pushback')).toBe('performance pushback');
    expect(scenarioLabel('application_volume_and_prioritization')).toBe(
      'application volume and prioritization',
    );
  });
});

/* The browser-held thread (issue #15) was retired by #46: threads live on the server, and
 * localStorage is only ever CLEARED now, on sign-out. */
describe('clearLegacyThreads', () => {
  it('removes every legacy thread key -- per-user and pre-sign-in -- and nothing else', () => {
    localStorage.setItem(STORAGE_KEY, '[]');
    localStorage.setItem(`${STORAGE_KEY}:7`, '[]');
    localStorage.setItem(`${STORAGE_KEY}:12`, '[]');
    localStorage.setItem('cs-theme', 'dark');

    clearLegacyThreads();

    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(localStorage.getItem(`${STORAGE_KEY}:7`)).toBeNull();
    expect(localStorage.getItem(`${STORAGE_KEY}:12`)).toBeNull();
    expect(localStorage.getItem('cs-theme')).toBe('dark');
    expect(localStorage.length).toBe(1);
  });

  it('swallows a storage failure: there is nothing in unavailable storage to clear', () => {
    localStorage.setItem(STORAGE_KEY, '[]');
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('SecurityError');
    });
    expect(() => clearLegacyThreads()).not.toThrow();
    expect(removeItem).toHaveBeenCalled();
  });
});

describe('carriedScenario', () => {
  const answered = (scenario_key: string) =>
    ({
      outcome: 'answered',
      answer: 'a',
      quote: 'q',
      citation: { label: 'L', call_filename: 'c.txt', pair_id: 1, scenario_key },
    }) as unknown as AskNarenResponse;
  const declined = { outcome: 'declined', reason: 'no_close_match', message: 'm' } as unknown as AskNarenResponse;
  const rendered = { outcome: 'rendered', kind: 'discovery' } as unknown as AskNarenResponse;

  it('is empty for an empty thread', () => {
    expect(carriedScenario([])).toBe('');
  });

  it('names the newest answered scenario, looking past later declines', () => {
    expect(
      carriedScenario([
        { question: 'a', response: answered('ramp') },
        { question: 'b', response: answered('performance_pushback') },
        { question: 'c', response: declined },
      ]),
    ).toBe('performance_pushback');
  });

  it('never walks back past a newer answer that is about many situations', () => {
    // The service stops at the most recent answered or rendered turn (`threads.last_answer`)
    // and asks rather than reaching back, so naming the older scenario would claim a carry
    // that will not happen.
    expect(
      carriedScenario([
        { question: 'a', response: answered('performance_pushback') },
        { question: 'd', response: rendered },
      ]),
    ).toBe('');
  });

  it('names a rendered turn’s scenario when that is the newest one carried', () => {
    expect(
      carriedScenario([
        { question: 'a', response: answered('ramp') },
        { question: 'b', response: { ...maximal.sequence, scenario_key: 'budget_pressure' } as AskNarenResponse },
      ]),
    ).toBe('budget_pressure');
  });

  it('is empty when nothing in the thread carries a scenario', () => {
    expect(carriedScenario([{ question: 'c', response: declined }, { question: 'd', response: rendered }])).toBe('');
  });
});

describe('thread JSON', () => {
  const createdAt = new Date('2026-09-01T10:00:00.000Z');
  const lastTurnAt = new Date('2026-09-02T11:30:00.000Z');
  const summary = { id: 3, title: 'Pausing spend', renamed: true, createdAt, lastTurnAt, turnCount: 1 };

  it('serialises a summary with ISO dates', () => {
    expect(summaryJson(summary)).toEqual({
      id: 3,
      title: 'Pausing spend',
      renamed: true,
      createdAt: '2026-09-01T10:00:00.000Z',
      lastTurnAt: '2026-09-02T11:30:00.000Z',
      turnCount: 1,
    });
  });

  it('serialises a thread with its turns, keeping the response verbatim', () => {
    const response = { outcome: 'declined', reason: 'no_close_match', message: 'm' } as AskNarenResponse;
    const json = threadJson({
      ...summary,
      turns: [{ position: 0, question: 'q', response, askedAt: createdAt, answeredAt: lastTurnAt }],
    } as unknown as Parameters<typeof threadJson>[0]);
    expect(json.id).toBe(3);
    expect(json.turns).toEqual([
      {
        position: 0,
        question: 'q',
        response,
        askedAt: '2026-09-01T10:00:00.000Z',
        answeredAt: '2026-09-02T11:30:00.000Z',
      },
    ]);
  });
});
