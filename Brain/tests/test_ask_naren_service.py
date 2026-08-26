"""ask_naren/service.py -- the HTTP contract, over a real socket against a stubbed
answerer. No gateway, no Postgres, no embeddings."""
import json
import threading

import httpx
import pytest

from ask_naren import service

ANSWER = {"declined": False, "answer": "Reframe on their own baseline.",
          "quote": "their own baseline", "citation": {"label": "a_call.txt"},
          "match": {"cosine": 0.71, "scenario_key": "performance_pushback"}}


@pytest.fixture
def serve_with():
    """Runs the real server on an ephemeral port with whatever answerer a test supplies."""
    servers = []

    def _start(answerer):
        httpd = service.build_server(answerer, host="127.0.0.1", port=0)
        servers.append(httpd)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield _start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def test_a_situation_gets_the_answerers_response_unchanged(serve_with):
    """The HTTP layer is transport only: whatever the answerer decided is what a caller
    reads, with no reshaping in between for the frontend to have to know about."""
    base = serve_with(lambda situation: ANSWER)
    r = httpx.post(f"{base}/ask", json={"situation": "cost per hire is too high"})
    assert r.status_code == 200
    assert r.json() == ANSWER


def test_the_situation_reaches_the_answerer_verbatim(serve_with):
    seen = []
    base = serve_with(lambda situation: (seen.append(situation), ANSWER)[1])
    httpx.post(f"{base}/ask", json={"situation": "  client is angry about spend  "})
    assert seen == ["  client is angry about spend  "]


def test_a_decline_is_a_successful_response_not_an_error(serve_with):
    """A decline is Ask Naren working correctly. Returning it as an HTTP error would make
    every caller treat conservative behaviour as an outage."""
    decline = {"declined": True, "reason": "no_close_match", "message": "No close match."}
    base = serve_with(lambda situation: decline)
    r = httpx.post(f"{base}/ask", json={"situation": "anything"})
    assert r.status_code == 200
    assert r.json()["declined"] is True


def test_a_blank_situation_is_rejected_without_reaching_the_answerer(serve_with):
    called = []
    base = serve_with(lambda situation: called.append(situation) or ANSWER)
    r = httpx.post(f"{base}/ask", json={"situation": "   "})
    assert r.status_code == 400
    assert called == []


def test_a_missing_situation_field_is_rejected(serve_with):
    base = serve_with(lambda situation: ANSWER)
    assert httpx.post(f"{base}/ask", json={"question": "wrong key"}).status_code == 400


def test_a_malformed_body_is_rejected_rather_than_crashing_the_server(serve_with):
    base = serve_with(lambda situation: ANSWER)
    r = httpx.post(f"{base}/ask", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400
    # the server is still answering afterwards
    assert httpx.post(f"{base}/ask", json={"situation": "still up"}).status_code == 200


def test_an_answerer_failure_reads_as_a_decline_not_a_traceback(serve_with):
    """A gateway outage or a dropped VPN must not put a stack trace in front of a CSM. The
    status distinguishes it from a genuine decline for whoever is debugging."""
    def explode(situation):
        raise RuntimeError("gateway unreachable")

    base = serve_with(explode)
    r = httpx.post(f"{base}/ask", json={"situation": "anything"})
    assert r.status_code == 503
    body = r.json()
    assert body["declined"] is True
    assert body["reason"] == "service_error"
    assert body["message"]
    assert "gateway unreachable" not in json.dumps(body)


def test_health_reports_readiness_without_spending_a_generation(serve_with):
    called = []
    base = serve_with(lambda situation: called.append(situation) or ANSWER)
    r = httpx.get(f"{base}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert called == []


def test_an_unknown_path_is_a_404(serve_with):
    base = serve_with(lambda situation: ANSWER)
    assert httpx.post(f"{base}/answer", json={"situation": "x"}).status_code == 404
    assert httpx.get(f"{base}/ask").status_code == 404


def test_responses_are_json(serve_with):
    base = serve_with(lambda situation: ANSWER)
    r = httpx.post(f"{base}/ask", json={"situation": "x"})
    assert r.headers["content-type"].startswith("application/json")


def test_an_idle_client_connection_does_not_block_the_next_caller(serve_with):
    """Requests are served one at a time on purpose (see the module docstring), so a
    keep-alive connection left open by one caller must not hold the service hostage: with
    HTTP/1.1 keep-alive on a serial server, the next CSM's question waits on a socket
    nobody is using. Each response closes its connection instead."""
    base = serve_with(lambda situation: ANSWER)
    lingering = httpx.Client()
    assert lingering.post(f"{base}/ask", json={"situation": "first"}).status_code == 200
    try:
        r = httpx.post(f"{base}/ask", json={"situation": "second"}, timeout=3.0)
        assert r.status_code == 200
    finally:
        lingering.close()
