"""Tests for Layer C's describe step -- batching and the inputs it is given.

Design: docs/superpowers/specs/2026-08-12-layer-c-profile-rebuild-design.md sections 3
and 3.2.

WHY BATCHING IS A CORRECTNESS CONCERN AND NOT A COST ONE. Today
_describe_milestones_batch groups 5 milestones drawn across ALL scenarios, and the prompt
tells the model to "write EACH independently … do not let one item influence another".
That rule exists to stop contamination between unrelated scenarios -- and it is the wrong
rule inside a single rubric, where a criterion can only be written to be distinguishable
from its siblings if it can see them. Grouping per scenario is what makes showing siblings
possible at all.

Pure grouping logic only; no Gemma, no DB, no torch.
"""
from v2.layer_c import group_describe_items_by_scenario as group


def _item(scenario, order, total=3):
    return {"id": f"{scenario}::{order}", "scenario_key": scenario,
            "order": order, "total": total, "clauses": [f"clause {order}"]}


def test_every_milestone_of_a_scenario_lands_in_one_batch():
    items = [_item("alpha", 1), _item("alpha", 2), _item("alpha", 3)]
    batches = group(items)

    assert len(batches) == 1
    assert [i["order"] for i in batches[0]] == [1, 2, 3]


def test_two_scenarios_never_share_a_batch():
    """The whole point. A batch containing two scenarios cannot show siblings without
    also showing unrelated criteria, which is the contamination the old rule guarded
    against."""
    items = [_item("alpha", 1), _item("beta", 1), _item("alpha", 2)]
    batches = group(items)

    assert len(batches) == 2
    for batch in batches:
        assert len({i["scenario_key"] for i in batch}) == 1


def test_order_within_a_scenario_is_preserved():
    """milestone_id is the array POSITION. If grouping reorders a scenario's items, every
    id downstream shifts and existing milestone_performance rows silently repoint at a
    different criterion -- the failure milestone_ids' docstring exists to prevent."""
    items = [_item("alpha", 1), _item("beta", 9), _item("alpha", 2), _item("alpha", 3)]
    alpha = next(b for b in group(items) if b[0]["scenario_key"] == "alpha")

    assert [i["order"] for i in alpha] == [1, 2, 3]


def test_items_arriving_out_of_order_are_still_grouped_together():
    """_collect_describe_items walks scenarios in dict order, but a caller that
    interleaves must not produce two batches for one scenario -- that would silently
    reintroduce sibling blindness for the split half."""
    items = [_item("alpha", 1), _item("beta", 1), _item("alpha", 2), _item("beta", 2)]
    batches = group(items)

    assert len(batches) == 2
    assert sorted(len(b) for b in batches) == [2, 2]


def test_grouping_is_deterministic_across_calls():
    """Two runs over the same items must produce the same batches, or a re-run reshuffles
    which criteria saw which siblings and the comparison between arms is confounded."""
    items = [_item("beta", 1), _item("alpha", 1), _item("beta", 2)]

    assert [[i["id"] for i in b] for b in group(items)] == \
           [[i["id"] for i in b] for b in group(list(items))]


def test_no_item_is_dropped_or_duplicated():
    items = [_item("alpha", 1), _item("beta", 1), _item("gamma", 1), _item("alpha", 2)]
    flat = [i["id"] for b in group(items) for i in b]

    assert sorted(flat) == sorted(i["id"] for i in items)


def test_an_empty_item_list_produces_no_batches():
    assert group([]) == []


def test_a_single_milestone_scenario_still_gets_its_own_batch():
    """A one-milestone rubric has no siblings to show, which is fine -- but it must not be
    merged with another scenario to fill the call, because that reintroduces exactly the
    cross-scenario contamination this grouping exists to prevent."""
    batches = group([_item("alpha", 1, total=1), _item("beta", 1, total=1)])

    assert len(batches) == 2
