"""layer_d/signals.py -- moment assembly with score_client_turns patched.

Same reasoning as test_ego_trap_signal_check.py's similarity tests: hand-built
similarity matrices pin the RULE without touching the embedder or Pinecone.
"""
import numpy as np
import pytest

from ego_trap.transcript_parser import EgoTrapRole, EgoTrapTurn
from layer_d import signals as sig_mod
from layer_d.signals import is_substantive_reply  # noqa: E402
from layer_d.signals import Moment, SignalScorer, csm_response_text, detect_moments, unverified_speakers

C, S, J = EgoTrapRole.CLIENT, EgoTrapRole.CSM, EgoTrapRole.OTHER_JOVEO


def t(i, role, text, speaker=None):
    return EgoTrapTurn(index=i, speaker_raw=speaker or role.value, role=role,
                       text=text, call_id="call1")


SCEN_MAP = {"coach": {"is_coachable": True}, "sink": {"is_coachable": False}}


def patch_scores(monkeypatch, table):
    """score_client_turns driven by an explicit text -> (coach_sim, sink_sim) table."""
    def fake(texts, scenario_map):
        keys = ["coach", "sink"]
        sims = np.array([table.get(x, (0.0, 1.0)) for x in texts], dtype=float)
        return keys, [False, True], sims
    monkeypatch.setattr(sig_mod.signal_check, "score_client_turns", fake)


def test_scorer_admits_when_coachable_wins_and_rejects_sink_wins(monkeypatch):
    patch_scores(monkeypatch, {"real": (0.9, 0.2), "junk": (0.1, 0.8)})
    s = SignalScorer(SCEN_MAP, margin=0.95, cap=1)
    s.prime(["real", "junk"])
    assert s.admit("real") == ["coach"]
    assert s.admit("junk") is None
    assert s.admit("") is None


def test_scorer_lazily_primes_unseen_text(monkeypatch):
    patch_scores(monkeypatch, {"late": (0.9, 0.1)})
    s = SignalScorer(SCEN_MAP, margin=0.95, cap=1)
    assert s.admit("late") == ["coach"]


def test_detect_moments_builds_the_full_record(monkeypatch):
    patch_scores(monkeypatch, {"we are drowning": (0.9, 0.2)})
    turns = [
        t(0, C, "we are drowning", "Alexa"),
        t(1, S, "let me pull the funnel."),
        t(2, S, "do you have UTM tags?"),
        t(3, C, "not sure", "Alexa"),
    ]
    s = SignalScorer(SCEN_MAP, margin=0.95, cap=1)
    [m] = detect_moments(turns, "call1", s, arm="today")
    assert m == Moment(
        call_id="call1", scenario_key="coach", candidate_scenario_keys=("coach",),
        trigger_text="we are drowning", signal_turn_index=0, via="last_turn",
        response_outcome="csm",
        response_text="let me pull the funnel. do you have UTM tags?",
    )
    assert m.moment_id == "call1:t0"
    assert m.source_ref == "turn:0"


def test_detect_moments_arm_e_recovers_filler_ended_block(monkeypatch):
    patch_scores(monkeypatch, {
        "real question": (0.9, 0.2),
        "sounds good": (0.1, 0.8),
        "real question sounds good": (0.85, 0.3),
    })
    turns = [
        t(0, C, "real question", "Alexa"),
        t(1, C, "sounds good", "Alexa"),
        t(2, S, "answer."),
    ]
    s = SignalScorer(SCEN_MAP, margin=0.95, cap=1)
    assert detect_moments(turns, "c", s, arm="today") == []
    [m] = detect_moments(turns, "c", s, arm="e")
    assert m.via == "stitched"
    assert m.signal_turn_index == 1
    assert m.response_text == "answer."


def test_teammate_reply_is_deferral_with_empty_response_text(monkeypatch):
    patch_scores(monkeypatch, {"question": (0.9, 0.2)})
    turns = [t(0, C, "question", "Alexa"), t(1, J, "teammate answers")]
    s = SignalScorer(SCEN_MAP, margin=0.95, cap=1)
    [m] = detect_moments(turns, "c", s, arm="today")
    assert m.response_outcome == "other_joveo"
    assert m.response_text == ""


def test_csm_response_text_excludes_teammate_turns():
    turns = [t(0, C, "q"), t(1, J, "teammate noise"), t(2, S, "csm reply"), t(3, C, "next")]
    assert csm_response_text(turns, 0) == "csm reply"


# ------------------------------------------------------------- interjection guard

def test_fragment_csm_reply_is_classified_as_interjection(monkeypatch):
    """The read-through's real defect: an interruption artifact ("So the last.")
    gets graded as a loss because SOMETHING csm-shaped followed the client turn.
    Below the substantiveness bar, response_outcome must NOT be "csm" -- the text
    itself stays intact so it's still visible in the stored event."""
    patch_scores(monkeypatch, {"real question": (0.9, 0.2)})
    turns = [
        t(0, C, "real question", "Alexa"),
        t(1, S, "So the last."),
    ]
    s = SignalScorer(SCEN_MAP, margin=0.95, cap=1)
    [m] = detect_moments(turns, "call1", s, arm="today")
    assert m.response_outcome == "interjection"
    assert m.response_text == "So the last."


@pytest.mark.parametrize("backchannel", [
    "Sounds good. Sounds good. Okay.",                     # decided the only `never` (§11b)
    "Okay. Sounds good. Sounds good.",
    "Got it. Sounds good. Sounds good.",
    "Yep. Sounds good. Cool. I know over time.",
    "Wait a minute. Hang hang on a second.",
    "Hi, Jim. Hello. Hey. Hi. Welcome.",
    "Got it. Got it. Makes sense. Okay. Yeah. Makes sense. I'll have to ask.",
    "Sounds good. Awesome. Cool. Okay. Thanks, everyone. Have a great weekend. Thank you.",
])
def test_real_backchannels_that_passed_v3_are_interjections(backchannel):
    """The _v4 hole: every one of these was graded as the CSM's reply on the
    production run (>= 5 content words by count). Repetition must not count twice,
    and a run of two-word acknowledgements is not a clause."""
    assert not is_substantive_reply(backchannel)


@pytest.mark.parametrize("reply", [
    "Let me walk you through the pixel firing setup.",
    "So our application form is just going to be a simple first name, last name, email, phone number, and the resume.",
    # NB: "You can place this directly on the header. It will still work." has only
    # four distinct content words and fails BOTH the v3 and v4 rules -- that is the
    # floor the project-wide bar already set, not something _v4 added.
    "You can place the universal pixel directly on the header of every page.",
    "Some publishers are okay to send candidates directly to the apply page, so which is a form.",
])
def test_short_real_replies_stay_substantive(reply):
    assert is_substantive_reply(reply)


def test_substantive_csm_reply_stays_csm(monkeypatch):
    """A short-but-real answer should not be misclassified: this pins that the
    guard is the SAME _is_substantive rule everywhere else, not a stricter one --
    still fires True as long as the reply clears 5 content words."""
    patch_scores(monkeypatch, {"real question": (0.9, 0.2)})
    turns = [
        t(0, C, "real question", "Alexa"),
        t(1, S, "Let me walk you through the pixel firing setup."),
    ]
    s = SignalScorer(SCEN_MAP, margin=0.95, cap=1)
    [m] = detect_moments(turns, "call1", s, arm="today")
    assert m.response_outcome == "csm"


# ------------------------------------------------------------------ fail closed

def test_unverified_speakers_flags_unknown_clients():
    turns = [t(0, C, "hi", "Alexa Smith"), t(1, C, "yo", "Mystery Person"), t(2, S, "r")]
    out = unverified_speakers(turns, frozenset({"alexa"}))
    assert out == {"Mystery Person"}


def test_unverified_speakers_prefix_matches_both_directions():
    turns = [t(0, C, "hi", "Alexa"), t(1, C, "yo", "Bob Jones"), t(2, S, "r")]
    assert unverified_speakers(turns, frozenset({"alexa smith", "bob"})) == set()


def test_unverified_speakers_ignores_non_client_roles():
    turns = [t(0, S, "hi", "Madhumita"), t(1, J, "yo", "Naren")]
    assert unverified_speakers(turns, frozenset()) == set()
