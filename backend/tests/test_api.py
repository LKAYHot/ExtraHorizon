"""Backend integration with substituted providers: HTTP/SSE chat, the vision WebSocket
(emotion engine driven by the labelled simulation or real frames), reset, isolation and
the local-only guards."""

from __future__ import annotations

import re
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


def read_until(ws, predicate, limit: int = 400) -> dict:
    for _ in range(limit):
        m = ws.receive_json()
        if predicate(m):
            return m
    raise AssertionError("message not received")


def sync(ws) -> list[dict]:
    """Everything the server sent so far (a ping/pong round trip marks the end)."""
    token = time.monotonic_ns()
    ws.send_json({"type": "ping", "t": token})
    out = []
    while True:
        m = ws.receive_json()
        if m["type"] == "pong" and m["t"] == token:
            return out
        out.append(m)


def simulate(ws, emotion: str, seconds: float, intensity: float = 0.85) -> list[dict]:
    """Drive the labelled Demo simulation for a while (10 Hz); returns what the server sent."""
    msgs: list[dict] = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        ws.send_json({"type": "sim", "enabled": True, "emotion": emotion, "intensity": intensity})
        msgs += sync(ws)
        time.sleep(0.1)
    return msgs


def last(msgs: list[dict], kind: str) -> dict:
    return [m for m in msgs if m["type"] == kind][-1]


def open_vision(c: TestClient, sid: str):
    cm = c.websocket_connect(f"/api/vision?session_id={sid}")
    ws = cm.__enter__()
    assert ws.receive_json()["type"] == "hello"
    assert ws.receive_json()["type"] == "snapshot"
    return cm, ws


# ---------------------------------------------------------------------- health
def test_health_reports_every_component():
    with client_for() as c:
        h = c.get("/api/health").json()
    assert h["status"] == "ok" and h["boot_id"] and h["persona"] == "Rika"
    assert h["llm"]["configured"] is True and h["llm"]["provider"] == "fake"
    assert h["vision"]["available"] is False
    assert h["tts"]["provider"] == "mock" and h["stt"]["provider"] == "mock"
    assert h["emotion"]["sensitivity"] == "balanced" and h["emotion"]["switch_hold_s"] == 1.0


# ---------------------------------------------------------------------- streaming chat
def test_stream_is_delivered_to_the_end_and_committed():
    llm = FakeLLM()
    with client_for(llm) as c:
        sid = new_sid()
        r, ev = chat(c, sid)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert names(ev)[0] == "meta" and names(ev)[-1] == "done"
        meta = ev[0][1]
        assert meta["turn_no"] == 1 and meta["source"] == "text"
        assert meta["emotion_context"]["available"] is False and meta["emotion_context"]["note"] is None
        assert "".join(d["text"] for n, d in ev if n == "delta") == llm.text
        done = ev[-1][1]
        assert done["finish_reason"] == "stop" and done["ttft_ms"] is not None and done["interrupted"] is False
        st = state(c, sid)
        assert [m["role"] for m in st["messages"]] == ["user", "assistant"]
        assert st["messages"][1]["id"] == meta["assistant_message_id"]
        assert [m["kind"] for m in st["timeline"]["markers"]] == ["answer"]


@pytest.mark.parametrize("failure", ["error", "fail_mid"])
def test_llm_error_ends_the_stream_and_retry_succeeds(failure):
    llm = FakeLLM(script=[failure, "ok"])
    with client_for(llm) as c:
        sid = new_sid()
        _, ev = chat(c, sid)
        assert names(ev)[-1] == "error" and ev[-1][1]["retryable"] is True
        assert state(c, sid)["messages"] == []  # nothing half-committed
        _, ev = chat(c, sid)
        assert names(ev)[-1] == "done"
        assert len(state(c, sid)["messages"]) == 2
        assert llm.closed == 2  # the failed provider stream was closed too


@pytest.mark.parametrize("failure", ["hang", "stall"])
def test_timeout_finishes_loading_and_allows_retry(failure):
    llm = FakeLLM(script=[failure, "ok"])
    with client_for(llm) as c:
        sid = new_sid()
        t0 = time.monotonic()
        _, ev = chat(c, sid)
        assert time.monotonic() - t0 < 3.0  # bounded by the 0.4 s test timeouts, never "thinking" forever
        assert names(ev)[-1] == "error" and ev[-1][1]["code"] == "llm_timeout" and ev[-1][1]["retryable"]
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


def test_a_newer_question_supersedes_the_one_in_flight():
    import threading

    llm = FakeLLM(script=["slow", "ok"], text=" ".join(["word"] * 40))
    with client_for(llm, llm_idle_timeout_s=2.0) as c:
        sid = new_sid()
        out: dict = {}
        t = threading.Thread(target=lambda: out.setdefault("ev", chat(c, sid, "first")[1]))
        t.start()
        time.sleep(0.3)
        _, ev2 = chat(c, sid, "second")
        t.join(5)
        assert names(out["ev"])[-1] == "error" and out["ev"][-1][1]["code"] == "superseded"
        assert names(ev2)[-1] == "done"
        assert [m["text"] for m in state(c, sid)["messages"]][0] == "second"


# ---------------------------------------------------------------------- emotions → prompt
def test_simulated_expression_drives_engine_note_timeline_and_the_prompt():
    llm = FakeLLM()
    with client_for(llm) as c:
        sid = new_sid()
        cm, ws = open_vision(c, sid)
        try:
            simulate(ws, "neutral", 0.5)
            msgs = simulate(ws, "happiness", 2.2)
            em = last(msgs, "tick")["emotion"]
            assert em["status"] == "ok" and em["source"] == "simulation" and em["dominant"] == "happiness"
            assert set(em["probs"]) == {"anger", "contempt", "disgust", "fear", "happiness", "neutral", "sadness", "surprise"}
            note = last(msgs, "emotion_note")["context"]["note"]
            assert "clearly happy" in note and "looked neutral" in note
            _, ev = chat(c, sid)
            ctx = ev[0][1]["emotion_context"]
            assert ctx["available"] and ctx["dominant"] == "happiness" and ctx["source"] == "simulation"
            sent = [m["content"] for m in llm.requests[-1] if m["role"] == "system"]
            assert ctx["note"] in sent and not re.search(r"\d", ctx["note"])
            st = state(c, sid)
            assert st["messages"][1]["emotion_context"]["note"] == ctx["note"]
            kinds = [m["kind"] for m in st["timeline"]["markers"]]
            assert "emotion" in kinds and kinds[-1] == "answer"
            s = st["timeline"]["samples"][-1]
            assert s[1] == "ok" and s[2] == "simulation" and s[3] == "happiness" and len(s[4]) == 8
        finally:
            cm.__exit__(None, None, None)


def test_turning_the_simulation_off_makes_the_expression_unknown():
    with client_for() as c:
        sid = new_sid()
        cm, ws = open_vision(c, sid)
        try:
            simulate(ws, "sadness", 0.5)
            ws.send_json({"type": "sim", "enabled": False})
            tick = last(sync(ws), "tick")
            assert tick["emotion"]["status"] == "unknown" and tick["emotion"]["probs"] is None
            _, ev = chat(c, sid)
            assert ev[0][1]["emotion_context"]["available"] is False
        finally:
            cm.__exit__(None, None, None)


def test_recalibrate_and_sensitivity_over_the_vision_socket():
    with client_for() as c:
        sid = new_sid()
        cm, ws = open_vision(c, sid)
        try:
            ws.send_json({"type": "sensitivity", "level": "calm"})
            msg = [m for m in sync(ws) if m["type"] == "calibration"][-1]
            assert msg["calibration"]["sensitivity"] == "calm"
            ws.send_json({"type": "calibrate"})
            tick = [m for m in sync(ws) if m["type"] == "tick"][-1]
            assert tick["calibration"]["state"] == "collecting" and tick["emotion"]["status"] == "calibrating"
            snap = c.get(f"/api/session/{sid}/state").json()
            assert snap["emotion"]["status"] == "calibrating"
        finally:
            cm.__exit__(None, None, None)


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


def test_real_face_frame_through_the_socket(model_path, emotion_model_path, portrait_jpeg):
    """camera frame → MediaPipe → quality gate → on-device expression model → engine (no LLM)."""
    import cv2
    import numpy as np

    from extrahorizon.vision.service import VisionService

    img = cv2.imdecode(np.frombuffer(portrait_jpeg, np.uint8), cv2.IMREAD_COLOR)
    small = cv2.resize(img, (480, int(img.shape[0] * 480 / img.shape[1])))
    jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
    s = make_settings(vision_enabled=True, vision_model_path=model_path, emotion_model_path=emotion_model_path)
    with TestClient(create_app(s, llm=FakeLLM(), vision=VisionService(s))) as c:
        with c.websocket_connect(f"/api/vision?session_id={new_sid()}") as ws:
            assert ws.receive_json()["vision"]["available"] is True
            ws.receive_json()
            ws.send_bytes((1).to_bytes(4, "big") + jpeg)
            tick = read_until(ws, lambda m: m["type"] == "tick")
            v = tick["vision"]
            assert v["faces"] == 1 and len(v["boxes"]) == 1 and v["quality"] == "ok"
            assert abs(sum(v["raw"]["probs"].values()) - 1) < 0.01 and v["emotion_ms"] is not None
            # first the learner's relaxed face is learned (a smiling portrait here) …
            assert tick["emotion"]["status"] == "calibrating" and v["calibration"]["state"] == "collecting"
            seq = 1
            while tick["vision"]["calibration"]["state"] != "ready":
                assert seq < 80, "calibration never finished"
                time.sleep(0.1)
                seq += 1
                ws.send_bytes(seq.to_bytes(4, "big") + jpeg)
                tick = read_until(ws, lambda m: m["type"] == "tick" and m["seq"] == seq)
            # … then this very face reads as that person's neutral, not as their raw "happiness"
            assert tick["emotion"]["status"] == "ok" and tick["emotion"]["dominant"] == "neutral"
            assert tick["vision"]["raw"]["probs"]["happiness"] > 0.9
            two = np.hstack([small, cv2.flip(small, 1)])
            ws.send_bytes((2).to_bytes(4, "big") + cv2.imencode(".jpg", two)[1].tobytes())
            tick = read_until(ws, lambda m: m["type"] == "tick")
            assert tick["vision"]["faces"] == 2 and tick["vision"]["reason"] == "multiple_faces"
            assert tick["emotion"]["status"] == "unknown" and tick["emotion"]["probs"] is None
            ws.send_bytes(b"\x00\x00\x00\x07" + b"garbage bytes, not an image")
            tick = read_until(ws, lambda m: m["type"] == "tick" and m["seq"] == 7)
            assert tick["vision"]["reason"] == "bad_frame" and tick["emotion"]["status"] == "unknown"


def test_closing_the_vision_socket_turns_the_expression_unknown():
    with client_for() as c:
        sid = new_sid()
        cm, ws = open_vision(c, sid)
        simulate(ws, "happiness", 0.4)
        cm.__exit__(None, None, None)
        time.sleep(0.2)
        with c.websocket_connect(f"/api/vision?session_id={sid}") as ws:
            ws.receive_json()
            snap = ws.receive_json()
            assert snap["type"] == "snapshot"
            assert snap["emotion"]["status"] == "unknown" and snap["emotion"]["reason"] == "vision_disconnected"
            assert snap["context"]["available"] is False and snap["sim"]["enabled"] is False


# ---------------------------------------------------------------------- sessions
def test_reset_clears_chat_emotions_and_timeline():
    with client_for() as c:
        sid = new_sid()
        cm, ws = open_vision(c, sid)
        try:
            simulate(ws, "happiness", 0.5)
            chat(c, sid)
            assert c.post("/api/session/reset", json={"session_id": sid}).json()["ok"] is True
            assert read_until(ws, lambda m: m["type"] == "reset")["epoch"] == 1
            snap = read_until(ws, lambda m: m["type"] == "snapshot")
            assert snap["timeline"] == {"samples": [], "markers": []} and snap["emotion"] is None
            st = state(c, sid)
            assert st["messages"] == [] and st["timeline"]["samples"] == []
            assert c.post("/api/session/reset", json={"session_id": sid}).status_code == 200  # repeated reset is fine
        finally:
            cm.__exit__(None, None, None)


def test_sessions_do_not_share_state():
    with client_for() as c:
        a, b = new_sid(), new_sid()
        cm, ws = open_vision(c, a)
        simulate(ws, "anger", 0.4)
        cm.__exit__(None, None, None)
        chat(c, a)
        chat(c, b, "Hello from B")
        sa, sb = state(c, a), state(c, b)
        assert sb["timeline"]["samples"] == [] and len(sa["timeline"]["samples"]) > 0
        assert [m["text"] for m in sb["messages"]][0] == "Hello from B"
        c.post("/api/session/reset", json={"session_id": a})
        assert len(state(c, b)["messages"]) == 2


def test_second_socket_supersedes_the_first():
    with client_for() as c:
        sid = new_sid()
        cm, first = open_vision(c, sid)
        try:
            with c.websocket_connect(f"/api/vision?session_id={sid}") as second:
                assert second.receive_json()["type"] == "hello"
                assert read_until(first, lambda m: m["type"] == "superseded")
        finally:
            cm.__exit__(None, None, None)


# ---------------------------------------------------------------------- local-only guards
def test_cross_origin_requests_are_blocked():
    with client_for() as c:
        r = c.post("/api/chat", json={"session_id": new_sid(), "message": "hi"}, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
        ok = c.post("/api/chat", json={"session_id": new_sid(), "message": "hi"}, headers={"Origin": "http://127.0.0.1:5173"})
        assert ok.status_code == 200


def test_cross_origin_websockets_are_blocked():
    from starlette.testclient import WebSocketDenialResponse
    from starlette.websockets import WebSocketDisconnect

    with client_for() as c:
        for path in ("/api/vision", "/api/live"):
            with pytest.raises((WebSocketDisconnect, WebSocketDenialResponse)):
                with c.websocket_connect(f"{path}?session_id={new_sid()}", headers={"Origin": "https://evil.example"}) as ws:
                    ws.receive_json()


def test_wildcard_bind_never_accepts_arbitrary_hosts():
    """DNS rebinding: a page on evil.example resolving to this machine must be rejected."""
    with client_for(host="0.0.0.0") as c:
        assert c.get("/api/health", headers={"Host": "evil.example:8765"}).status_code == 400
        assert c.get("/api/health", headers={"Host": "127.0.0.1:8765"}).status_code == 200
    with client_for(host="0.0.0.0", allowed_hosts=["tutor.lan"]) as c:
        # an explicitly allowed LAN name gets through the host check — but another machine
        # still needs the access key (none configured here → remote access is off)
        r = c.get("/api/health", headers={"Host": "tutor.lan:8765"})
        assert r.status_code == 403 and r.json()["code"] == "remote_disabled"


def test_broken_opencv_disables_vision_but_never_the_chat():
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
