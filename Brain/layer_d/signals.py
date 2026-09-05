"""Moment assembly: segmentation + sink-relative signal detection + response window.

The admit/reject decision is ego_trap.signal_check's similarity machinery, imported
rather than copied (one definition of the rule; it moves here when ego_trap's
rubric-era modules retire). The rule: score against the FULL scenario map, sinks
included -- a sink winning is the only rejection mechanism, and it is the only
signal-detection approach that has ever survived measurement in this project
(absolute floors admitted 100% of turns; the sink comparison rejects 57-61%).

Embedding spend note: every unique candidate text is embedded ONCE per process
(memoized below) through preprocessing.embedder, which routes by
tuning.embedding.backend. On the live `gateway` backend a novel CSM turn is a paid
vector; calibration/layer_d_bands.py (C0) pre-pays and measures the corpus before
any production run.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ego_trap import signal_check
from ego_trap.transcript_parser import (
    EgoTrapRole, EgoTrapTurn, classify_response_outcome, turns_until_next_client,
)
from layer_d import segmentation


@dataclass(frozen=True)
class Moment:
    """One scored unit: a client move and the CSM's reply to it."""
    call_id: str
    scenario_key: str
    candidate_scenario_keys: tuple[str, ...]
    trigger_text: str
    signal_turn_index: int
    via: str                        # "last_turn" | "stitched"
    response_outcome: str           # "csm" | "other_joveo" | "none" | "interjection"
    response_text: str              # the CSM's turns in the window, joined

    @property
    def moment_id(self) -> str:
        return f"{self.call_id}:t{self.signal_turn_index}"

    @property
    def source_ref(self) -> str:
        return f"turn:{self.signal_turn_index}"


class SignalScorer:
    """Memoized admit() over signal_check.score_client_turns.

    Same shape as the calibration trial's Scorer, re-homed for production use
    (production must not import calibration). Batch-embeds every unseen text on
    prime(), so arm E's two-phase need (per-turn verdicts, then stitched verdicts)
    costs two embedding batches per transcript, not one per turn.
    """

    def __init__(self, scenario_map: dict[str, dict], *, margin: float, cap: int):
        self.map = scenario_map
        self.margin = margin
        self.cap = cap
        self.keys: list[str] = []
        self.is_sink: list[bool] = []
        self._sims: dict[str, np.ndarray] = {}

    def prime(self, texts: list[str]) -> None:
        todo = sorted({t for t in texts if t and t not in self._sims})
        if not todo:
            return
        keys, is_sink, sims = signal_check.score_client_turns(todo, self.map)
        if not keys:
            raise RuntimeError("score_client_turns returned no scenario keys")
        self.keys, self.is_sink = keys, is_sink
        for i, t in enumerate(todo):
            self._sims[t] = sims[i]

    def admit(self, text: str) -> list[str] | None:
        if not text:
            return None
        if text not in self._sims:
            self.prime([text])
        return signal_check.select_signal(
            self._sims[text], self.keys, self.is_sink,
            margin=self.margin, cap=self.cap,
        )


def csm_response_text(turns: list[EgoTrapTurn], anchor_index: int) -> str:
    """The CSM's own turns between the anchor and the next client turn, joined.
    Teammate turns are excluded: only the CSM's execution is gradable evidence."""
    window = turns_until_next_client(turns, anchor_index)
    return " ".join(t.text for t in window if t.role == EgoTrapRole.CSM).strip()


def detect_moments(
    turns: list[EgoTrapTurn],
    call_id: str,
    scorer: SignalScorer,
    *,
    arm: str,
) -> list[Moment]:
    """Every admitted moment in one transcript, under one segmentation arm.

    Primes the scorer for the whole transcript up front (block last-turns plus, for
    arm e, every individual block turn), so admit() never single-embeds in the loop.

    THE INTERJECTION GUARD: a "csm" response window whose joined text fails
    _is_substantive (the same >=5-content-word bar used everywhere else in this
    project to mean "is this a real utterance or noise") is reclassified as
    "interjection" -- an interruption artifact or backchannel ("So the last.",
    "Yeah I hear.") caught by the response window, not a real reply. This is a
    STRUCTURAL rule on the response's shape, not a cosine/semantic filter --
    per-item embedding threshold filters have failed 9 times in this project.
    Recorded like a deferral (never graded), but kept out of "other_joveo" so it
    doesn't silently change the already-reported deferral rate.
    """
    from v1.layer_b import _is_substantive  # lazy: spaCy model load

    blocks = segmentation.client_blocks(turns)
    to_prime = [b[-1].text for b in blocks]
    if arm == "e":
        to_prime += [t.text for b in blocks for t in b]
    scorer.prime(to_prime)

    moments: list[Moment] = []
    for sig in segmentation.segment_moves(turns, arm, scorer.admit):
        outcome = classify_response_outcome(turns, sig.signal_turn_index)
        response_text = csm_response_text(turns, sig.signal_turn_index)
        if outcome == "csm" and not _is_substantive(response_text):
            outcome = "interjection"
        moments.append(Moment(
            call_id=call_id,
            scenario_key=sig.scenario_keys[0],
            candidate_scenario_keys=tuple(sig.scenario_keys),
            trigger_text=sig.trigger_text,
            signal_turn_index=sig.signal_turn_index,
            via=sig.via,
            response_outcome=outcome,
            response_text=response_text,
        ))
    return moments


def unverified_speakers(
    turns: list[EgoTrapTurn],
    known_clients_lower: frozenset[str],
) -> set[str]:
    """Speakers classified CLIENT who are not on the verified client roster.

    transcript_parser._classify FAILS OPEN: anyone not matched to the CSM or the
    Joveo list becomes CLIENT, so an unlisted Joveo colleague's internal chatter
    becomes coaching signals (87 of 113 speakers were unclassified on the 100-call
    run). The pipeline fails CLOSED instead: a transcript with unverified client
    speakers is EXCLUDED and reported unless the operator explicitly allows it.
    Same prefix-matching rule as _classify, so 'Alexa' on the roster covers
    'Alexa Smith' in the transcript and vice versa.
    """
    out: set[str] = set()
    for t in turns:
        if t.role != EgoTrapRole.CLIENT:
            continue
        s = t.speaker_raw.strip().lower()
        if not any(s == k or s.startswith(k) or k.startswith(s)
                   for k in known_clients_lower):
            out.add(t.speaker_raw.strip())
    return out
