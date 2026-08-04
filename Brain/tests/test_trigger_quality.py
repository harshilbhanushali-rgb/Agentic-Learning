"""shared/trigger_quality.py -- content signals shared by the sink-rescue design
(docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md, Status update 3)
and the trigger-quality-gate design
(docs/superpowers/specs/2026-08-04-layer-b-trigger-quality-gate-design.md).
Real spaCy runs here (these are structural/linguistic properties, not embeddings) --
this tests the signal functions themselves, not their callers.
"""
from shared.trigger_quality import concrete_entity_density


def test_concrete_entity_density_high_for_specific_text():
    text = "We use Workday and Phenom in Chicago with about 30 recruiters."
    assert concrete_entity_density(text) > 0.0


def test_concrete_entity_density_zero_for_generic_filler():
    text = "Yeah, I think that sounds fine to me, whatever works for you guys."
    assert concrete_entity_density(text) == 0.0
