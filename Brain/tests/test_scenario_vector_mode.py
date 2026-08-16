"""`layer_a.scenario_vector_mode` -- which register of a scenario's text is embedded.

Spec: docs/superpowers/specs/2026-08-16-layer-a-routing-method-design.md

The load-bearing test here is `test_concat_is_byte_identical_to_the_pre_flag_expression`:
this flag sits at the choke point feeding Layer B matching, Layer C relevance filtering,
Layer D rubric lookup and the response-taxonomy auto-pass, so the default path must produce
exactly the bytes it produced before the flag existed -- not merely "equivalent" text.
"""
from __future__ import annotations

import pytest

from shared import scenario_vectors as sv
from shared.tuning import load_tuning


def pre_flag_expression(info: dict) -> str:
    """Verbatim copy of `scenario_text` as it stood before the flag was added (git a3f4891).

    Kept as a literal here on purpose: comparing the implementation against itself would
    pass no matter what the implementation did.
    """
    return info.get("business_description", "") + " " + " ".join(
        info.get("keyphrases", []) or [])


CASES = [
    {"business_description": "Client hesitates over spend", "keyphrases": ["cost per activation", "budget"]},
    {"business_description": "Only prose here", "keyphrases": []},
    {"business_description": "Only prose here", "keyphrases": None},
    {"business_description": "", "keyphrases": ["radius search"]},
    {"keyphrases": ["launching this RFP"]},                  # no description key at all
    {"business_description": "no keyphrases key"},
    {},
]


# -- the byte-identity guarantee ---------------------------------------------------------

@pytest.mark.parametrize("info", CASES)
def test_concat_is_byte_identical_to_the_pre_flag_expression(info):
    assert sv.scenario_text(info, mode="concat") == pre_flag_expression(info)


def test_concat_preserves_even_the_failure_mode():
    """A None description has always raised TypeError here. Quietly "fixing" that under the
    default mode would make the flag-off path something other than what shipped."""
    info = {"business_description": None, "keyphrases": ["x"]}
    with pytest.raises(TypeError):
        pre_flag_expression(info)
    with pytest.raises(TypeError):
        sv.scenario_text(info, mode="concat")


def test_the_shipped_default_is_concat():
    """If this fails, production behaviour changed without anyone deciding to change it."""
    assert load_tuning().layer_a.scenario_vector_mode == "concat"


# -- the modes ---------------------------------------------------------------------------

def test_keyphrases_mode_drops_the_analyst_prose():
    info = {"business_description": "Client hesitates over spend",
            "keyphrases": ["cost per activation", "budget"]}
    assert sv.scenario_text(info, mode="keyphrases") == "cost per activation budget"


def test_prose_mode_drops_the_keyphrases():
    info = {"business_description": "Client hesitates over spend",
            "keyphrases": ["cost per activation"]}
    assert sv.scenario_text(info, mode="prose") == "Client hesitates over spend"


def test_modes_differ_from_concat_on_a_populated_scenario():
    info = {"business_description": "prose", "keyphrases": ["kp"]}
    got = {m: sv.scenario_text(info, mode=m) for m in sv.MODES}
    assert len(set(got.values())) == 3, got


# -- the empty-field fallback ------------------------------------------------------------

def test_empty_target_field_falls_back_to_concat_and_warns(caplog):
    """A VISIBLE fallback. Embedding "" would hand every text-less scenario the same
    degenerate vector, which then wins matches at random."""
    info = {"business_description": "prose only", "keyphrases": []}
    with caplog.at_level("WARNING"):
        out = sv.scenario_text(info, mode="keyphrases")
    assert out == pre_flag_expression(info)
    assert any("falling back to concat" in r.message for r in caplog.records)


def test_fallback_never_returns_empty_for_a_scenario_that_has_any_text():
    for info in ({"business_description": "p", "keyphrases": []},
                 {"business_description": "", "keyphrases": ["k"]}):
        for m in sv.MODES:
            assert sv.scenario_text(info, mode=m).strip()


# -- validation --------------------------------------------------------------------------

def test_an_unknown_mode_raises_rather_than_silently_defaulting():
    """The `ego_trap/settings.py` lesson: a config value that reads as authoritative while
    doing nothing is worse than either state."""
    with pytest.raises(ValueError, match="scenario_vector_mode must be one of"):
        sv.scenario_text({"business_description": "x"}, mode="keyphrase")


def test_batch_path_and_single_path_agree(monkeypatch):
    """`build_scenario_vecs` resolves the mode once and threads it; `scenario_vec` resolves
    its own. They must not drift -- Layer B uses the batch path and Layer D the single one."""
    seen = []
    monkeypatch.setattr(sv.embedder, "embed_document",
                        lambda texts: seen.extend(texts) or [[0.0] for _ in texts])
    info = {"business_description": "prose", "keyphrases": ["kp"]}
    for m in sv.MODES:
        seen.clear()
        sv.build_scenario_vecs({"k": info}, mode=m)
        batch = list(seen)
        seen.clear()
        sv.scenario_vec(info, mode=m)
        assert batch == seen, m


def test_build_scenario_vecs_reads_the_CONFIG_once_not_per_scenario(monkeypatch):
    """The requirement is no repeated CONFIG reads, not no repeated validation.

    An earlier version of this test asserted `_resolve_mode` was called once and failed at
    26 -- because `build_scenario_vecs` resolves once and `scenario_text` then re-validates
    the mode it was handed. That re-validation is free and defensive: with an explicit mode
    `_resolve_mode` never reaches `get_tuning`. Asserting on the config read tests the thing
    that actually costs something and the thing that actually matters.
    """
    reads = []
    monkeypatch.setattr(sv, "get_tuning",
                        lambda: reads.append(1) or type("T", (), {
                            "layer_a": type("A", (), {"scenario_vector_mode": "concat"})})())
    monkeypatch.setattr(sv.embedder, "embed_document", lambda texts: [[0.0] for _ in texts])
    scenarios = {f"k{i}": {"business_description": "d", "keyphrases": []} for i in range(25)}
    sv.build_scenario_vecs(scenarios)
    assert len(reads) == 1, f"{len(reads)} config reads for 25 scenarios"

    reads.clear()
    sv.build_scenario_vecs(scenarios, mode="keyphrases")
    assert reads == [], "an explicit mode must not consult tuning.yaml at all"
