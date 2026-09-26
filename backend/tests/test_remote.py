"""Remote demo access (e.g. behind Cloudflare Tunnel): who counts as "this computer", the access
key, the cookie, the brute-force brake, and what a remote browser is told (transport, lighter
camera profile). The tunnel's requests arrive from 127.0.0.1 — only the headers tell them apart."""

from __future__ import annotations

import time

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from extrahorizon.access import AccessTokens, LoginLimiter, transport
from extrahorizon.app import create_app

from .conftest import FakeLLM, FakeVision, make_settings, new_sid

KEY = "demo-access-key-for-tests-only"
PUBLIC = "https://demo.example.com"
# what Cloudflare Tunnel adds to every request it forwards
CF = {"host": "demo.example.com", "origin": PUBLIC, "cf-connecting-ip": "203.0.113.7", "cf-ray": "8f0-TEST",
      "x-forwarded-for": "203.0.113.7", "x-forwarded-proto": "https"}


def remote_client(**settings) -> TestClient:
    base = {"public_url": PUBLIC, "access_key": KEY}
    base.update(settings)
    return TestClient(create_app(make_settings(**base), llm=FakeLLM(), vision=FakeVision()))


def login(c: TestClient, key: str = KEY, headers: dict | None = None):
    return c.post("/api/access", json={"key": key}, headers=headers or CF)


def cookie_from(r) -> str:
    raw = r.headers["set-cookie"]
    return raw.split(";", 1)[0]  # "eh_access=v1.…"


def test_transport_tells_the_tunnel_from_this_computer():
    base = {"type": "http", "client": ("127.0.0.1", 50000)}

    def scope(**h):
        return {**base, "headers": [(k.encode(), v.encode()) for k, v in h.items()]}

    assert transport(scope(host="127.0.0.1:8765")) == "local"
    assert transport(scope(host="localhost:8080")) == "local"
    assert transport(scope(host="[::1]:8765")) == "local"
    assert transport(scope(host="demo.example.com", **{"cf-connecting-ip": "1.2.3.4"})) == "cloudflare"
    assert transport(scope(host="127.0.0.1:8080", **{"cf-ray": "abc"})) == "cloudflare"  # a tunnel to 127.0.0.1
    assert transport(scope(host="127.0.0.1:8080", **{"x-forwarded-for": "1.2.3.4"})) == "proxy"
    assert transport(scope(host="demo.example.com")) == "network"  # a public name without a proxy header
    assert transport({"type": "http", "client": ("192.168.1.20", 5), "headers": [(b"host", b"127.0.0.1")]}) == "network"


def test_remote_requests_are_refused_without_a_configured_key():
    with remote_client(access_key=None) as c:
        r = c.get("/api/health", headers=CF)
        assert r.status_code == 403 and r.json()["code"] == "remote_disabled"
        st = c.get("/api/access", headers=CF).json()
        assert st == {"required": True, "ok": False, "configured": False, "transport": "cloudflare", "public_url": PUBLIC}
        assert login(c).status_code == 403
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect(f"/api/vision?session_id={new_sid()}", headers=CF) as ws:
                ws.receive_json()
        assert e.value.code == 4403
        assert c.get("/api/health").status_code == 200  # this computer is unaffected


def test_the_access_key_unlocks_the_api_with_a_safe_cookie():
    with remote_client() as c:
        assert c.get("/api/access", headers=CF).json()["ok"] is False
        r = c.get("/api/health", headers=CF)
        assert r.status_code == 401 and r.json()["code"] == "access_required"
        assert c.get("/api/docs", headers=CF).status_code == 401  # every /api route is guarded
        wrong = login(c, "not-the-key")
        assert wrong.status_code == 401 and wrong.json()["code"] == "wrong_key" and "set-cookie" not in wrong.headers
        ok = login(c)
        assert ok.status_code == 200 and ok.json()["ok"] is True
        raw = ok.headers["set-cookie"].lower()
        assert "httponly" in raw and "samesite=strict" in raw and "secure" in raw and "max-age=1209600" in raw
        assert KEY.lower() not in raw  # the cookie holds a signed timestamp, never the key
        h = {**CF, "cookie": cookie_from(ok)}
        health = c.get("/api/health", headers=h)
        assert health.status_code == 200 and health.json()["client"] == {"transport": "cloudflare"}
        assert c.get("/api/access", headers=h).json()["ok"] is True
        sid = new_sid()
        assert c.post("/api/session/reset", json={"session_id": sid}, headers=h).status_code == 200
        out = c.delete("/api/access", headers=h)
        assert out.status_code == 200 and "eh_access=" in out.headers["set-cookie"]


def test_this_computer_never_needs_the_key():
    with remote_client() as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/access").json() == {"required": False, "ok": True, "configured": True,
                                               "transport": "local", "public_url": PUBLIC}
        assert c.get("/api/health").json()["client"] == {"transport": "local"}


def test_the_ui_shell_is_public_so_it_can_ask_for_the_key():
    with remote_client() as c:
        r = c.get("/", headers=CF)
        assert r.status_code == 200 and "ExtraHorizon" in r.text


def test_tampered_expired_or_rotated_cookies_are_rejected():
    tokens = AccessTokens(KEY, 3600)
    good = tokens.issue()
    assert tokens.valid(good)
    version, issued, sig = good.split(".")
    assert not tokens.valid(f"{version}.{int(issued) + 1}.{sig}")  # changed timestamp
    assert not tokens.valid(f"{version}.{issued}.{sig[:-2]}AA")  # changed signature
    assert not tokens.valid(tokens.issue(now=time.time() - 7200))  # older than the max age
    assert not tokens.valid(tokens.issue(now=time.time() + 3600))  # from the future
    assert not AccessTokens("another-key-entirely", 3600).valid(good)  # the key was changed
    assert not tokens.valid("") and not tokens.valid("junk") and not tokens.valid("v1.x.y")
    assert tokens.check_key(KEY) and not tokens.check_key(KEY + " ")


def test_wrong_keys_are_braked_per_client_and_overall():
    with remote_client() as c:
        for _ in range(8):
            assert login(c, "guess").status_code == 401
        blocked = login(c)  # even the right key has to wait now
        assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
        assert blocked.json()["code"] == "too_many_attempts"
        other = login(c, headers={**CF, "cf-connecting-ip": "198.51.100.9"})  # another client is fine
        assert other.status_code == 200
    lim = LoginLimiter(per_ip=3, total=5, window_s=60)
    for i in range(5):
        lim.failed(f"10.0.0.{i}", now=0.0)
    assert lim.retry_after("10.0.0.99", now=1.0) > 0  # the overall brake
    assert lim.retry_after("10.0.0.99", now=61.0) == 0


def test_a_remote_browser_gets_the_tunnel_transport_and_a_lighter_camera_profile():
    with remote_client() as c:
        h = {**CF, "cookie": cookie_from(login(c))}
        with c.websocket_connect(f"/api/vision?session_id={new_sid()}", headers=h) as ws:
            hello = ws.receive_json()
        assert hello["client_is_loopback"] is False and hello["transport"] == "cloudflare"
        assert hello["config"]["max_fps"] == 8 and hello["config"]["jpeg_quality"] == 0.7
        with c.websocket_connect(f"/api/live?session_id={new_sid()}", headers=h) as ws:
            assert ws.receive_json()["type"] == "hello"
        with c.websocket_connect(f"/api/vision?session_id={new_sid()}") as ws:  # this computer
            local = ws.receive_json()
        assert local["client_is_loopback"] is True and local["config"]["max_fps"] == 12
        with pytest.raises(WebSocketDisconnect) as e:  # no cookie → closed before anything is sent
            with c.websocket_connect(f"/api/live?session_id={new_sid()}", headers=CF) as ws:
                ws.receive_json()
        assert e.value.code == 4401


def test_login_is_same_origin_only_and_the_public_name_is_the_only_new_host():
    with remote_client() as c:
        evil = c.post("/api/access", json={"key": KEY}, headers={**CF, "origin": "https://evil.example"})
        assert evil.status_code == 403 and evil.json()["code"] == "forbidden_origin"
        assert c.get("/api/access", headers={**CF, "host": "other.example.com"}).status_code == 400
    with pytest.raises(ValueError):
        make_settings(public_url="demo.example.com")  # not an origin
    with pytest.raises(ValueError):
        make_settings(public_url="https://demo.example.com/path")
    assert make_settings(public_url="https://Demo.Example.com/").public_url == "https://demo.example.com"
    assert make_settings(access_key="short").access_configured is False  # too short to be a real key
