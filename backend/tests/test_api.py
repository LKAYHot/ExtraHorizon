"""Backend integration with a substituted LLM (spec §7.3) + the full chain over
HTTP/SSE and the vision WebSocket (controlled signal = labelled simulation)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from extrahorizon.app import create_app
from extrahorizon.llm import OpenAIChat

from .conftest import FakeLLM, FakeVision, make_settings, new_sid, parse_sse


def client_for(llm=None, vision=None, **settings) -> TestClient:
    app = create_app(make_settings(**settings), llm=llm or FakeLLM(), vision=vision or FakeVision())
    return TestClient(app)


def chat(client: TestClient, sid: str, message: str = "Explain recursion to me.", **extra):
    r = client.post("/api/chat", json={"session_id": sid, "message": message, **extra})
    return r, parse_sse(r.text) if r.status_code == 200 else []


def names(events) -> list[str]:
    return [n for n, _ in events]


def state(client: TestClient, sid: str) -> dict:
    return client.get(f"/api/session/{sid}/state").json()


def trigger_event(ws, seconds: float = 0.6) -> dict:
    """Drive the labelled simulation input high until the engine fires an event."""
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        ws.send_json({"type": "sim", "enabled": True, "value": 0.95})
        while True:
            m = ws.receive_json()
            if m["type"] == "event" and m["event"]["kind"] == "possible_confusion":
                return m["event"]
            if m["type"] == "tick":
                break
        time.sleep(0.05)
    raise AssertionError("no event")


def read_until(ws, predicate, limit: int = 200) -> dict:
    for _ in range(limit):
        m = ws.receive_json()
        if predicate(m):
            return m
    raise AssertionError("message not received")


# ---------------------------------------------------------------------- health
def test_health_reports_llm_and_vision_status():
    with client_for() as c:
        h = c.get("/api/health").json()
    assert h["status"] == "ok" and h["boot_id"]
    assert h["llm"]["configured"] is True and h["llm"]["provider"] == "fake"
    assert h["vision"]["available"] is False
    assert h["engine"]["threshold"] == 0.65


# ---------------------------------------------------------------------- streaming
def test_stream_is_delivered_to_the_end_and_committed():
    llm = FakeLLM(text="Recursion means a function calls itself until a base case.")
    with client_for(llm) as c:
        sid = new_sid()
        r, ev = chat(c, sid)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert names(ev)[0] == "meta" and names(ev)[-1] == "done"
        text = "".join(d["text"] for n, d in ev if n == "delta")
        assert text == llm.text
        done = ev[-1][1]
        assert done["finish_reason"] == "stop" and done["ttft_ms"] is not None
        st = state(c, sid)
        assert [m["role"] for m in st["messages"]] == ["user", "assistant"]
        assert st["messages"][1]["id"] == ev[0][1]["assistant_message_id"]
        assert [m["kind"] for m in st["timeline"]["markers"]] == ["answer"]


@pytest.mark.parametrize("failure", ["error", "fail_mid"])
def test_llm_error_ends_the_stream_and_retry_succeeds(failure):
    llm = FakeLLM(script=[failure, "ok"])
    with client_for(llm) as c:
        sid = new_sid()
        _, ev = chat(c, sid)
        assert names(ev)[-1] == "error" and ev[-1][1]["retryable"] is True
        assert state(c, sid)["messages"] == []  # nothing half-committed
        _, ev = chat(c, sid)  # the UI's Retry re-sends the same message
        assert names(ev)[-1] == "done"
        assert [m["text"] for m in state(c, sid)["messages"]][0] == "Explain recursion to me."
        assert len(state(c, sid)["messages"]) == 2
        assert llm.closed == 2  # the failed provider stream was closed too


@pytest.mark.parametrize("failure,code", [("hang", "llm_timeout"), ("stall", "llm_timeout")])
def test_timeout_finishes_loading_and_allows_retry(failure, code):
    llm = FakeLLM(script=[failure, "ok"])
    with client_for(llm) as c:
        sid = new_sid()
        t0 = time.monotonic()
        _, ev = chat(c, sid)
        assert time.monotonic() - t0 < 3.0  # bounded by the 0.4 s test timeouts, never "thinking" forever
        assert names(ev)[-1] == "error" and ev[-1][1]["code"] == code and ev[-1][1]["retryable"]
        assert state(c, sid)["messages"] == []
        _, ev = chat(c, sid)
        assert names(ev)[-1] == "done"


def test_missing_api_key_is_a_clear_immediate_error():
    s = make_settings(llm_provider="openai", openai_api_key=None)
    with TestClient(create_app(s, llm=OpenAIChat(s), vision=FakeVision())) as c:
        assert c.get("/api/health").json()["llm"]["configured"] is False
        t0 = time.monotonic()
        _, ev = chat(c, new_sid())
        assert time.monotonic() - t0 < 1.0
        assert names(ev) == ["meta", "error"]
        assert ev[-1][1]["code"] == "llm_not_configured" and ev[-1][1]["retryable"] is False


def test_validation_errors_are_plain_http_errors():
    with client_for() as c:
        assert c.post("/api/chat", json={"session_id": "not-a-uuid", "message": "hi"}).status_code == 422
        r = c.post("/api/chat", json={"session_id": new_sid(), "message": "   "})
        assert r.status_code == 422 and r.json()["code"] == "empty_message"


# ---------------------------------------------------------------------- vision failure
def test_vision_failure_does_not_disable_chat():
    with client_for(vision=FakeVision(available=False, reason="model_missing")) as c:
        sid = new_sid()
        with c.websocket_connect(f"/api/vision?session_id={sid}") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello" and hello["vision"]["available"] is False
            ws.receive_json()  # snapshot
            ws.send_bytes(b"\x00\x00\x00\x01" + b"\xff\xd8not-really-a-jpeg")
            err = read_until(ws, lambda m: m["type"] == "error")
            assert err["code"] == "vision_unavailable"
            _, ev = chat(c, sid)
            assert names(ev)[-1] == "done"


def test_broken_frames_become_unknown_not_crashes(model_path):
    from extrahorizon.vision.service import VisionService

    s = make_settings(vision_enabled=True, vision_model_path=model_path)
    with TestClient(create_app(s, llm=FakeLLM(), vision=VisionService(s))) as c:
        sid = new_sid()
        with c.websocket_connect(f"/api/vision?session_id={sid}") as ws:
            assert ws.receive_json()["vision"]["available"] is True
            ws.receive_json()
            ws.send_bytes(b"\x00\x00\x00\x07" + b"garbage bytes, not an image")
            tick = read_until(ws, lambda m: m["type"] == "tick")
            assert tick["seq"] == 7 and tick["vision"]["quality"] == "unknown" and tick["vision"]["reason"] == "bad_frame"
            assert tick["engine"]["status"] == "unknown" and tick["engine"]["smoothed"] is None
            _, ev = chat(c, sid)
            assert names(ev)[-1] == "done"


def test_real_face_frame_through_the_socket(model_path, portrait_jpeg):
    """camera frame → local MediaPipe → quality gate → calibration (no LLM involved)."""
    import cv2
    import numpy as np

    from extrahorizon.vision.service import VisionService

    img = cv2.imdecode(np.frombuffer(portrait_jpeg, np.uint8), cv2.IMREAD_COLOR)
    small = cv2.resize(img, (480, int(img.shape[0] * 480 / img.shape[1])))
    jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 75])[1].tobytes()
    s = make_settings(vision_enabled=True, vision_model_path=model_path)
    with TestClient(create_app(s, llm=FakeLLM(), vision=VisionService(s))) as c:
        with c.websocket_connect(f"/api/vision?session_id={new_sid()}") as ws:
            ws.receive_json()
            ws.receive_json()
            ws.send_bytes((1).to_bytes(4, "big") + jpeg)
            tick = read_until(ws, lambda m: m["type"] == "tick")
            v = tick["vision"]
            assert v["faces"] == 1 and len(v["boxes"]) == 1
            assert v["quality"] == "calibrating" and v["features"]["brow_lower"] >= 0
            assert tick["engine"]["status"] == "calibrating" and tick["engine"]["smoothed"] is None
            two = np.hstack([small, cv2.flip(small, 1)])
            ws.send_bytes((2).to_bytes(4, "big") + cv2.imencode(".jpg", two)[1].tobytes())
            tick = read_until(ws, lambda m: m["type"] == "tick")
            assert tick["vision"]["faces"] == 2 and tick["vision"]["reason"] == "multiple_faces"
            assert tick["engine"]["status"] == "unknown"


# ---------------------------------------------------------------------- the demo chain
def test_full_chain_event_then_adapted_answer_then_reset():
    llm = FakeLLM()
    with client_for(llm) as c:
        sid = new_sid()
        with c.websocket_connect(f"/api/vision?session_id={sid}") as ws:
            ws.receive_json()
            ws.receive_json()
            _, ev = chat(c, sid)
            answer_id = ev[-1][1]["assistant_message_id"]
            read_until(ws, lambda m: m["type"] == "marker" and m["marker"]["kind"] == "answer")

            event = trigger_event(ws)
            assert event["status"] == "offered" and event["answer_id"] == answer_id
            assert event["source"] == "simulation" and event["smoothed"] > 0.65

            r = c.post("/api/chat", json={"session_id": sid, "mode": "explain_differently", "event_id": event["id"]})
            ev2 = parse_sse(r.text)
            meta = ev2[0][1]
            assert names(ev2)[-1] == "done"
            assert meta["adaptation"]["event_id"] == event["id"]
            assert meta["adaptation"]["strategy"]["id"] == "analogy_example_steps"
            assert meta["adaptation"]["signal"]["source"] == "simulation"
            assert meta["user_message"]["mode"] == "explain_differently"
            upd = read_until(ws, lambda m: m["type"] == "event_update")
            assert upd["event"]["status"] == "used"
            # the provider saw the note — and the previous answer
            sent = llm.requests[-1]
            assert any("Adaptation note" in m["content"] for m in sent if m["role"] == "system")
            assert any(m["role"] == "assistant" for m in sent)

            # the same event cannot be used twice
            again = c.post("/api/chat", json={"session_id": sid, "mode": "explain_differently", "event_id": event["id"]})
            assert again.status_code == 409

            # reset clears chat, events, timeline and the cooldown
            assert c.post("/api/session/reset", json={"session_id": sid}).json()["ok"] is True
            assert read_until(ws, lambda m: m["type"] == "reset")["epoch"] == 1
            snap = read_until(ws, lambda m: m["type"] == "snapshot")
            assert snap["events"] == [] and snap["timeline"] == {"samples": [], "markers": []}
            st = state(c, sid)
            assert st["messages"] == [] and st["events"] == [] and st["timeline"]["samples"] == []
            # no cooldown left: a new answer + sustained signal fires again right away
            chat(c, sid)
            assert trigger_event(ws)["status"] == "offered"
            assert c.post("/api/session/reset", json={"session_id": sid}).status_code == 200  # repeated reset is fine


def test_explain_differently_needs_an_active_event():
    with client_for() as c:
        sid = new_sid()
        chat(c, sid)
        r = c.post("/api/chat", json={"session_id": sid, "mode": "explain_differently", "event_id": "ev_000000000000"})
        assert r.status_code == 409 and r.json()["code"] == "no_active_event"


def test_a_new_question_expires_a_pending_offer():
    with client_for() as c:
        sid = new_sid()
        with c.websocket_connect(f"/api/vision?session_id={sid}") as ws:
            ws.receive_json()
            ws.receive_json()
            chat(c, sid)
            event = trigger_event(ws)
            chat(c, sid, "Something else entirely")
            upd = read_until(ws, lambda m: m["type"] == "event_update")
            assert upd["event"]["id"] == event["id"] and upd["event"]["status"] == "expired"
            r = c.post("/api/chat", json={"session_id": sid, "mode": "explain_differently", "event_id": event["id"]})
            assert r.status_code == 409


def test_event_without_an_answer_is_not_offered():
    with client_for() as c:
        sid = new_sid()
        with c.websocket_connect(f"/api/vision?session_id={sid}") as ws:
            ws.receive_json()
            ws.receive_json()
            event = trigger_event(ws)
            assert event["answer_id"] is None and event["status"] == "unattached"


def test_sessions_do_not_share_state():
    with client_for() as c:
        a, b = new_sid(), new_sid()
        with c.websocket_connect(f"/api/vision?session_id={a}") as ws:
            ws.receive_json()
            ws.receive_json()
            chat(c, a)
            trigger_event(ws)
        chat(c, b, "Hello from B")
        sa, sb = state(c, a), state(c, b)
        assert len(sa["events"]) == 1 and sb["events"] == []
        assert sb["timeline"]["samples"] == [] and len(sa["timeline"]["samples"]) > 0
        assert [m["text"] for m in sb["messages"]][0] == "Hello from B"
        c.post("/api/session/reset", json={"session_id": a})
        assert len(state(c, b)["messages"]) == 2


def test_second_socket_supersedes_the_first():
    with client_for() as c:
        sid = new_sid()
        with c.websocket_connect(f"/api/vision?session_id={sid}") as first:
            first.receive_json()
            first.receive_json()
            with c.websocket_connect(f"/api/vision?session_id={sid}") as second:
                assert second.receive_json()["type"] == "hello"
                assert read_until(first, lambda m: m["type"] == "superseded")


def test_cross_origin_requests_are_blocked():
    with client_for() as c:
        r = c.post(
            "/api/chat",
            json={"session_id": new_sid(), "message": "hi"},
            headers={"Origin": "https://evil.example"},
        )
        assert r.status_code == 403
        ok = c.post(
            "/api/chat",
            json={"session_id": new_sid(), "message": "hi"},
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        assert ok.status_code == 200


def test_broken_opencv_disables_vision_but_never_the_chat(tmp_path):
    """A classic Windows 'DLL load failed while importing cv2' must not take the chat down."""
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        """
        import sys
        sys.modules["cv2"] = None          # every `import cv2` now raises ImportError
        from fastapi.testclient import TestClient
        from extrahorizon.app import create_app
        from extrahorizon.vision.service import VisionService
        from tests.conftest import FakeLLM, make_settings, new_sid, parse_sse
        s = make_settings(vision_enabled=True)
        with TestClient(create_app(s, llm=FakeLLM(), vision=VisionService(s))) as c:
            vision = c.get("/api/health").json()["vision"]
            r = c.post("/api/chat", json={"session_id": new_sid(), "message": "hi"})
            print(vision["available"], [n for n, _ in parse_sse(r.text)][-1])
        """
    )
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120,
                         cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "False done"


def test_closing_the_vision_socket_turns_the_signal_unknown():
    with client_for() as c:
        sid = new_sid()
        with c.websocket_connect(f"/api/vision?session_id={sid}") as ws:
            ws.receive_json()
            ws.receive_json()
            for _ in range(3):
                ws.send_json({"type": "sim", "enabled": True, "value": 0.9})
                read_until(ws, lambda m: m["type"] == "tick")
        time.sleep(0.2)
        with c.websocket_connect(f"/api/vision?session_id={sid}") as ws:
            ws.receive_json()
            snap = ws.receive_json()
            assert snap["type"] == "snapshot"
            assert snap["engine"]["status"] == "unknown" and snap["engine"]["reason"] == "vision_disconnected"
            assert snap["engine"]["smoothed"] is None and snap["sim"]["enabled"] is False


def test_wildcard_bind_never_accepts_arbitrary_hosts():
    """DNS rebinding: a page on evil.example resolving to this machine must be rejected."""
    with client_for(host="0.0.0.0") as c:
        assert c.get("/api/health", headers={"Host": "evil.example:8765"}).status_code == 400
        assert c.get("/api/health", headers={"Host": "127.0.0.1:8765"}).status_code == 200
    with client_for(host="0.0.0.0", allowed_hosts=["tutor.lan"]) as c:
        assert c.get("/api/health", headers={"Host": "tutor.lan:8765"}).status_code == 200
