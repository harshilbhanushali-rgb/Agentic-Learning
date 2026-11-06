"""calibration/rebuild_stage_c_h2h.py -- packet build and scoring (Stage C head-to-head)."""
import json

import pytest

from calibration import ARTIFACTS_DIR
from calibration import rebuild_stage_c_h2h as c

NEEDED = [ARTIFACTS_DIR / f for f in c.LIVE_ARTIFACTS + ("pbf_rest_report.json",)]
pytestmark = pytest.mark.skipif(not all(p.exists() for p in NEEDED),
                                reason="live playbook artifacts not on this machine")


@pytest.fixture
def built(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "PACKET", tmp_path / "packet.txt")
    monkeypatch.setattr(c, "KEY", tmp_path / "key.json")
    c.build("rest", "union_base")          # live docs vs themselves: a mechanics check
    return json.loads((tmp_path / "key.json").read_text(encoding="utf-8")), tmp_path


def test_build_shape(built):
    key, tmp = built
    docs, items = key["docs"], key["items"]
    assert len(docs) == 2 * c.N_SITUATIONS
    for s in range(1, c.N_SITUATIONS + 1):
        assert {docs[f"D{s}a"]["side"], docs[f"D{s}b"]["side"]} == {"new", "old"}
    assert sum(v["kind"] == "neg" for v in items.values()) == c.N_NEG
    text = (tmp / "packet.txt").read_text(encoding="utf-8")
    assert all(f"[{i}]" in text for i in items)
    assert "new" not in json.dumps([l for l in text.splitlines() if l.startswith("-----")])


def test_build_refuses_to_overwrite(built):
    with pytest.raises(SystemExit):
        c.build("rest", "union_base")


def _reader(key, name, prefer):
    """Y on every item of the `prefer` side's docs, N elsewhere; planted quotes N."""
    ans = {}
    for i, v in key["items"].items():
        side = key["docs"][v["doc"]]["side"]
        ans[i] = "N" if v["kind"] == "neg" else ("Y" if side == prefer else "N")
    return {"_file": name, "answers": ans}


def test_score_new_wins_every_situation(built):
    key, _ = built
    res = c.score(key, [_reader(key, f"r{i}", "new") for i in range(3)])
    assert res["wins"]["new"] == c.N_SITUATIONS
    assert res["floors"]["pb0_all"] is True


def test_score_old_wins_keeps_incumbent(built):
    key, _ = built
    res = c.score(key, [_reader(key, f"r{i}", "old") for i in range(3)])
    assert res["verdict"] == "KEEP_INCUMBENT" and res["wins"]["old"] == c.N_SITUATIONS


def test_score_invalid_reader_is_not_counted(built):
    key, _ = built
    bad = _reader(key, "r3", "new")
    for i, v in key["items"].items():
        if v["kind"] == "neg":
            bad["answers"][i] = "Y"
    res = c.score(key, [_reader(key, "r1", "new"), _reader(key, "r2", "new"), bad])
    assert res["verdict"] == "INSTRUMENT_INCOMPLETE"


def test_score_refuses_partial(built):
    key, _ = built
    r = _reader(key, "r1", "new")
    r["answers"].pop(next(iter(r["answers"])))
    with pytest.raises(SystemExit):
        c.score(key, [r])
