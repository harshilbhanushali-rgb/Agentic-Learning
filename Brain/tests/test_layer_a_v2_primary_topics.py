"""Regression test for the primary-topic labeling batch (v2/layer_a.py).

Covers a real bug found 2026-07-30 on the first actual pipeline run to
exercise this code path: _finalize_primary_topics builds each subtopic
`record` without a "keywords" key, but _label_primary_topics_batch's prompt
formatting reads m['keywords'] -- a guaranteed KeyError the instant any
primary_topic group is labeled. Every prior "calibration" of this feature was
dry-run only (dry_run_layer_a.py never calls this function), so nothing
caught it until a real Gemma-backed run did.
"""
import re
import types

from v2 import layer_a


def test_finalize_primary_topics_does_not_crash_on_keywords_field(monkeypatch):
    monkeypatch.setattr(
        layer_a, "call_gemma",
        lambda prompt, keys: [{"id": "g0", "primary_topic_key": "pricing_topics",
                                "label": "Pricing", "description": "Pricing discussions",
                                "keyphrases": ["cost", "budget"]}],
    )

    class _Tuning:
        grouping_method = "nested"
        merge_cosine_threshold = 0.85

    by_key = {
        "pricing_objection": {
            "scenario_key": "pricing_objection",
            "business_description": "client pushes back on cost",
            "keywords": "price, cost, expensive",
            "macro_group_id": 0,
            "call_set": {"call1", "call2"},
            "is_coachable": True,
        },
    }

    fake_config = types.SimpleNamespace(gemma_api_keys=("fake-key",))
    rows = layer_a._finalize_primary_topics(by_key, _Tuning(), config=fake_config, total_calls=2)

    assert rows == [{
        "primary_topic_key": "pricing_topics",
        "label": "Pricing",
        "description": "Pricing discussions",
        "keyphrases": ["cost", "budget"],
        "grouping_method": "nested_cluster",
        "support_calls": 2,
        "support_subtopics": 1,
        "call_coverage": 1.0,
    }]
    # The member record is mutated in-place with the resolved primary topic.
    assert by_key["pricing_objection"]["primary_topic_key"] == "pricing_topics"
    assert by_key["pricing_objection"]["primary_topic"] == "Pricing"


def test_finalize_primary_topics_splits_a_mixed_macro_group_by_coachability(monkeypatch):
    """A single BERTopic macro_group_id containing both a coachable scenario
    and a sink can be geometrically real (centroids converge under
    averaging) -- see docs/superpowers/specs/2026-07-31-layer-a-primary-topic-
    coachability-split-design.md. _finalize_primary_topics must emit two
    primary_topics rows, not one blended row."""
    seen_group_counts = []

    def _fake_call_gemma(prompt, keys):
        # One row per group presented, keyed by its "gN" id -- proves
        # split_by_coachability ran BEFORE labeling saw the groups.
        group_ids = sorted(set(re.findall(r"id: (g\d+)", prompt)))
        seen_group_counts.append(len(group_ids))
        return [
            {"id": gid, "primary_topic_key": f"topic_{gid}", "label": gid,
             "description": "d", "keyphrases": []}
            for gid in group_ids
        ]

    monkeypatch.setattr(layer_a, "call_gemma", _fake_call_gemma)

    class _Tuning:
        grouping_method = "nested"
        merge_cosine_threshold = 0.85

    by_key = {
        "real_scenario": {
            "scenario_key": "real_scenario", "business_description": "desc",
            "keywords": "k", "macro_group_id": 0, "call_set": {"call1"},
            "is_coachable": True,
        },
        "backchannel_sink": {
            "scenario_key": "backchannel_sink", "business_description": "desc",
            "keywords": "k", "macro_group_id": 0, "call_set": {"call1"},
            "is_coachable": False,
        },
    }
    fake_config = types.SimpleNamespace(gemma_api_keys=("fake-key",))
    rows = layer_a._finalize_primary_topics(by_key, _Tuning(), config=fake_config, total_calls=1)

    assert seen_group_counts == [2]  # labeling saw 2 already-split groups, not 1 mixed one
    assert len(rows) == 2
    assert by_key["real_scenario"]["primary_topic_key"] != by_key["backchannel_sink"]["primary_topic_key"]


def test_label_primary_topics_batch_deduplicates_colliding_labels(monkeypatch):
    """Gemma labels each batch of _TOPIC_LABEL_BATCH_SIZE groups independently,
    so two separate batch calls can reinvent the same natural-language label
    for genuinely different groups -- confirmed in production: "Positive
    Client Sentiment" was assigned to both a 5-member and a 1-member group
    from two separate calls. primary_topic_key already gets a uniqueness
    suffix in this situation; the human-readable label must too, or a CSM
    browsing the taxonomy sees two indistinguishable rows."""

    def _fake_call_gemma(prompt, keys):
        # Every batch reinvents "Same Name" independently, exactly like two
        # separate Gemma calls landing on the same phrase would.
        group_ids = re.findall(r"id: (g\d+)", prompt)
        return [
            {"id": gid, "primary_topic_key": f"topic_{gid}", "label": "Same Name",
             "description": "d", "keyphrases": []}
            for gid in group_ids
        ]

    layer_a_module_batch_size = layer_a._TOPIC_LABEL_BATCH_SIZE
    monkeypatch.setattr(layer_a, "call_gemma", _fake_call_gemma)
    fake_config = types.SimpleNamespace(gemma_api_keys=("fake-key",))

    # One more group than a single batch holds, forcing 2 separate Gemma calls.
    groups = [
        [{"scenario_key": f"m{i}", "business_description": "d", "keywords": "k"}]
        for i in range(layer_a_module_batch_size + 1)
    ]
    labels = layer_a._label_primary_topics_batch(groups, fake_config)

    label_texts = [entry["label"] for entry in labels]
    assert len(label_texts) == len(set(label_texts)), f"labels not unique: {label_texts}"
    assert all(text.startswith("Same Name") for text in label_texts)


def test_label_primary_topics_batch_leaves_unique_labels_untouched(monkeypatch):
    monkeypatch.setattr(
        layer_a, "call_gemma",
        lambda prompt, keys: [{"id": "g0", "primary_topic_key": "pricing_topics",
                                "label": "Pricing", "description": "d", "keyphrases": []}],
    )
    fake_config = types.SimpleNamespace(gemma_api_keys=("fake-key",))
    groups = [[{"scenario_key": "m0", "business_description": "d", "keywords": "k"}]]
    labels = layer_a._label_primary_topics_batch(groups, fake_config)
    assert labels[0]["label"] == "Pricing"
