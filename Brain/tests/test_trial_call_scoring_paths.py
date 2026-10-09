"""Tests for calibration/trial_call_scoring.py's artifact paths and overwrite guard.

Pins audit F7 / remediation R6. `OUT` and `CKPT` were fixed paths written unconditionally,
so any run silently replaced any other -- and one already did: a 45-call artifact was
destroyed by a 30-call run under the same filename, and only its numbers survive in prose.

Two properties are pinned:
  - a tag applies to BOTH the artifact AND the checkpoint. A tag on the checkpoint alone is
    a real defect in this project's history: the cheap run resumes separately and then
    overwrites the expensive run's output anyway.
  - a SMALLER run cannot silently replace a bigger one.

No network, no DB, no LLM: pure path arithmetic and a tmp_path JSON file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from calibration import trial_call_scoring as tcs


# -- tagging --------------------------------------------------------------------------------

def test_untagged_paths_are_the_headline_names():
    out, ckpt = tcs.paths_for(None, smoke=False)
    assert out.name == "call_scoring_trial.json", out.name
    assert ckpt.name == "call_scoring_trial_ckpt.json", ckpt.name


def test_a_tag_applies_to_BOTH_the_artifact_and_the_checkpoint():
    out, ckpt = tcs.paths_for("control", smoke=False)
    assert "control" in out.name and "control" in ckpt.name, (
        "a tag on only one of the two lets a control run resume separately and then "
        "overwrite the headline artifact anyway")
    assert out != ckpt


def test_smoke_tags_itself_so_a_path_test_cannot_reach_the_real_filename():
    out, ckpt = tcs.paths_for(None, smoke=True)
    real, real_ckpt = tcs.paths_for(None, smoke=False)
    assert out != real and ckpt != real_ckpt, f"smoke wrote to the headline path: {out.name}"
    assert "smoke" in out.name and "smoke" in ckpt.name, (out.name, ckpt.name)


def test_an_explicit_tag_wins_over_the_smoke_default():
    out, _ = tcs.paths_for("probe", smoke=True)
    assert "probe" in out.name and "smoke" not in out.name, out.name


# -- the overwrite guard --------------------------------------------------------------------

def _write(path, **kw):
    path.write_text(json.dumps({"n_calls": kw.get("n_calls", 45),
                                "smoke": kw.get("smoke", False),
                                "model": "m", "seed": 42, "per_call": 1}), encoding="utf-8")


def test_a_smaller_run_cannot_silently_replace_a_bigger_one(tmp_path):
    out = tmp_path / "call_scoring_trial.json"
    _write(out, n_calls=45)
    with pytest.raises(SystemExit, match="REFUSING TO OVERWRITE"):
        tcs.guard_overwrite(out, n_calls=30, smoke=False, force=False)


def test_force_allows_it(tmp_path):
    out = tmp_path / "call_scoring_trial.json"
    _write(out, n_calls=45)
    tcs.guard_overwrite(out, n_calls=30, smoke=False, force=True)   # must not raise


def test_a_bigger_or_equal_run_may_replace(tmp_path):
    out = tmp_path / "call_scoring_trial.json"
    _write(out, n_calls=30)
    tcs.guard_overwrite(out, n_calls=45, smoke=False, force=False)
    tcs.guard_overwrite(out, n_calls=30, smoke=False, force=False)


def test_replacing_a_previous_SMOKE_artifact_is_always_allowed(tmp_path):
    out = tmp_path / "call_scoring_trial.json"
    _write(out, n_calls=99, smoke=True)
    tcs.guard_overwrite(out, n_calls=3, smoke=False, force=False)


def test_the_guard_is_reachable_before_any_scoring_happens():
    """It must be called with the INTENDED call count, before the paid loop.

    Checking only at write time refuses the run after the whole budget has been spent on
    it, which makes the guard worse than useless -- it costs the money and discards the
    result.
    """
    import inspect
    src = inspect.getsource(tcs.main)
    first_guard = src.index("guard_overwrite(")
    scoring_loop = src.index("for idx, fn in enumerate(picked")
    assert first_guard < scoring_loop, (
        "guard_overwrite must be called BEFORE the scoring loop, not only at write time")


def test_a_missing_or_unreadable_artifact_does_not_block_a_run(tmp_path):
    tcs.guard_overwrite(tmp_path / "absent.json", n_calls=1, smoke=False, force=False)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    tcs.guard_overwrite(bad, n_calls=1, smoke=False, force=False)


# -- transport parity (audit R7b) -----------------------------------------------------------

def test_the_gateway_uses_the_SAME_output_ceiling_as_the_ai_studio_path():
    """chat_json defaults to 8192; the scorer sets 16384. Not passing it halves the budget
    on ONE ARM of a transport comparison -- and truncation does not raise here, it returns
    fewer scenarios or fewer milestone ids, which reconcile to "not occurred" or default to
    "miss". Truncation therefore MANUFACTURES MISSES that look like real verdicts.
    """
    import inspect
    from ego_trap.call_scoring import _SCORING_MAX_OUTPUT_TOKENS
    from calibration.trial_gateway import GatewayClient

    gateway_default = inspect.signature(GatewayClient.chat_json).parameters["max_tokens"].default
    assert gateway_default != _SCORING_MAX_OUTPUT_TOKENS, (
        "fixture assumption gone: the gateway default now equals the scorer's ceiling, so "
        "this test no longer demonstrates anything")

    src = inspect.getsource(tcs._gateway_chat)
    assert "max_tokens=_SCORING_MAX_OUTPUT_TOKENS" in src, (
        f"the gateway wrapper must pass the scorer's ceiling ({_SCORING_MAX_OUTPUT_TOKENS}), "
        f"not inherit chat_json's default ({gateway_default})")


def test_chat_json_meta_carries_the_served_model_without_breaking_callers():
    """The response reports which model ANSWERED; callers were discarding it.

    It rides in the existing meta dict so all five `parsed, _ = gw.chat_json(...)` call
    sites keep working -- a third return value would have broken every one of them.
    """
    import inspect
    from calibration import trial_gateway

    src = inspect.getsource(trial_gateway.GatewayClient.chat_json)
    assert 'meta["served_model"] = data.get("model")' in src
    assert "return json.loads(content), meta" in src, (
        "chat_json must still return exactly two values")

    # every caller still destructures two values
    for mod in ("trial_call_scoring", "trial_adjudicate_gemini", "trial_grader_inputs"):
        text = (Path(trial_gateway.__file__).parent / f"{mod}.py").read_text(
            encoding="utf-8-sig")
        for line in text.splitlines():
            if "gw.chat_json(" in line and "=" in line:
                lhs = line.split("=")[0]
                assert lhs.count(",") == 1, f"{mod}: {line.strip()}"
