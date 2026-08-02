"""Regression test for a real crash hit 2026-07-31 mid-run: a raw
httpx.ReadError ("_ssl.c:2580") from a dropped SSL connection was not
recognized by _TRANSIENT_MARKERS' string matching, so it skipped retry
entirely and crashed the run on the first occurrence instead of backing off
like a 500/503/504 does. Fixed by also checking isinstance(e, httpx.TransportError),
the base class for every network-transport-level httpx exception, regardless
of its message wording.
"""
import httpx
import pytest

from shared import gemma


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, side_effects):
        self._side_effects = list(side_effects)
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        effect = self._side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return _FakeResponse(effect)


class _FakeClient:
    def __init__(self, side_effects):
        self.models = _FakeModels(side_effects)

    def __call__(self, *args, **kwargs):
        return self


def test_ssl_read_error_is_retried_not_raised_immediately(monkeypatch):
    read_error = httpx.ReadError("The operation did not complete (read) (_ssl.c:2580)")
    fake_models = _FakeModels([read_error, '{"ok": true}'])

    class _Client:
        def __init__(self, *a, **kw):
            self.models = fake_models

    monkeypatch.setattr("google.genai.Client", _Client)
    monkeypatch.setattr(gemma.time, "sleep", lambda seconds: None)

    result = gemma._call_once(
        prompt="p", api_key="k", model="gemma-4-31b-it",
        temperature=0.0, max_output_tokens=100, max_retries=5, escalate=False,
    )

    assert result == {"ok": True}
    assert fake_models.calls == 2  # first call raised, second call succeeded


def test_ssl_read_error_still_raises_gemma_error_once_retries_exhausted(monkeypatch):
    read_error = httpx.ReadError("The operation did not complete (read) (_ssl.c:2580)")
    fake_models = _FakeModels([read_error, read_error])

    class _Client:
        def __init__(self, *a, **kw):
            self.models = fake_models

    monkeypatch.setattr("google.genai.Client", _Client)
    monkeypatch.setattr(gemma.time, "sleep", lambda seconds: None)

    with pytest.raises(gemma.GemmaError):
        gemma._call_once(
            prompt="p", api_key="k", model="gemma-4-31b-it",
            temperature=0.0, max_output_tokens=100, max_retries=2, escalate=False,
        )
