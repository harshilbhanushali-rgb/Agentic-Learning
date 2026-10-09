"""pipeline.gateway_chat -- the malformed-generation resample, with the client faked.

The defect this pins: on the first 33-playbook run, ONE malformed generation
(non-JSON) killed a whole scenario because chat_json raises straight through.
gateway_chat must resample malformed generations (fresh sample each time under
no_cache) and still propagate every other error untouched.
"""
import pytest

import shared.gateway as gw
from layer_d import pipeline
from shared.gateway import GatewayError


class FakeClient:
    """Stands in for GatewayClient; scripted responses per call."""
    script = []          # list of Exception or parsed-value entries
    calls = []

    def __init__(self, *a, **k):
        pass

    def chat_json(self, prompt, **kw):
        FakeClient.calls.append(kw)
        item = FakeClient.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, {"usage": 1}


@pytest.fixture
def fake_client(monkeypatch):
    monkeypatch.setattr(gw, "GatewayClient", FakeClient)
    monkeypatch.setattr(pipeline, "get_tuning", lambda: __import__("types").SimpleNamespace(
        layer_d=__import__("types").SimpleNamespace(
            grader_model="m-test", grader_reasoning_effort="medium")))
    FakeClient.script, FakeClient.calls = [], []
    return FakeClient


def test_malformed_generation_is_resampled(fake_client):
    fake_client.script = [GatewayError("non-JSON from m: boom"), ([{"ok": 1}])]
    chat = pipeline.gateway_chat()
    assert chat("p") == [{"ok": 1}]
    assert len(fake_client.calls) == 2


def test_three_malformed_samples_raise_the_last_error(fake_client):
    fake_client.script = [GatewayError("non-JSON 1"), GatewayError("empty completion"),
                          GatewayError("non-JSON 3")]
    chat = pipeline.gateway_chat()
    with pytest.raises(GatewayError, match="non-JSON 3"):
        chat("p")
    assert len(fake_client.calls) == 3


def test_other_gateway_errors_propagate_immediately(fake_client):
    fake_client.script = [GatewayError("HTTP 429: rate limit")]
    chat = pipeline.gateway_chat()
    with pytest.raises(GatewayError, match="429"):
        chat("p")
    assert len(fake_client.calls) == 1          # no resample on non-parse errors


def test_chat_sends_the_tuned_model_effort_and_limits(fake_client):
    fake_client.script = [([],)]
    # the tuple above would confuse unpacking; use a plain value instead
    fake_client.script = [[]]

    # chat_json returns (parsed, usage); FakeClient wraps parsed itself
    chat = pipeline.gateway_chat()
    chat("p")
    [kw] = fake_client.calls
    assert kw["model"] == "m-test"
    assert kw["reasoning_effort"] == "medium"
    assert kw["max_tokens"] == 65536
    assert kw["no_cache"] is True


def test_effort_none_is_not_sent(fake_client, monkeypatch):
    monkeypatch.setattr(pipeline, "get_tuning", lambda: __import__("types").SimpleNamespace(
        layer_d=__import__("types").SimpleNamespace(
            grader_model="m-test", grader_reasoning_effort="none")))
    fake_client.script = [[]]
    pipeline.gateway_chat()("p")
    assert fake_client.calls[-1]["reasoning_effort"] is None
