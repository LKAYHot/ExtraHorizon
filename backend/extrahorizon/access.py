"""Remote access: who counts as "this computer", and the access key for everyone else.

The server always binds to loopback. For the remote demo an HTTPS tunnel (Cloudflare Tunnel's
``cloudflared``) runs on the same computer and forwards the public URL to it, so *every* tunnel
request arrives from 127.0.0.1 — the peer address alone says nothing. A request is **local**
only if all of these hold:

* the peer is a loopback address,
* no proxy header is present (Cloudflare always adds ``CF-Connecting-IP`` / ``CF-Ray``; other
  proxies ``X-Forwarded-For`` / ``Forwarded``),
* the ``Host`` is a loopback name (not the public name, not a DNS-rebinding name).

Everything else is **remote** and needs the access key (``EH_ACCESS_KEY``): the browser posts it
once to ``/api/access`` and gets an HttpOnly, SameSite=Strict cookie holding a signed timestamp
(never the key). Without a configured key remote requests are refused. The UI shell (static
files) stays public so it can show the key prompt; every ``/api/*`` route and both WebSockets
are guarded.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
import time
from collections import deque
from http.cookies import SimpleCookie

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger("extrahorizon.access")

COOKIE = "eh_access"
LOOPBACK_NAMES = {"127.0.0.1", "localhost", "::1", "testserver", "testclient"}
CLOUDFLARE_HEADERS = ("cf-connecting-ip", "cf-ray")
PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded")
OPEN_PATHS = ("/api/access",)  # the key prompt itself


def headers_of(scope: Scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def _host_name(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):  # [::1]:8765
        return host[1:].split("]", 1)[0]
    if host.count(":") == 1:  # name:port
        return host.split(":", 1)[0]
    return host


def _is_loopback_address(addr: str | None) -> bool:
    if not addr:
        return False
    if addr in LOOPBACK_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return ip.is_loopback or (ip.version == 6 and ip.ipv4_mapped is not None and ip.ipv4_mapped.is_loopback)


def transport(scope: Scope, headers: dict[str, str] | None = None) -> str:
    """``local`` (this computer) · ``cloudflare`` (Cloudflare Tunnel) · ``proxy`` (another reverse
    proxy) · ``network`` (another machine connected directly)."""
    h = headers if headers is not None else headers_of(scope)
    if any(k in h for k in CLOUDFLARE_HEADERS):
        return "cloudflare"
    if any(k in h for k in PROXY_HEADERS):
        return "proxy"
    client = scope.get("client")
    peer = client[0] if client else None
    if _is_loopback_address(peer) and _host_name(h.get("host", "")) in LOOPBACK_NAMES:
        return "local"
    return "network"


def is_local(scope: Scope) -> bool:
    return transport(scope) == "local"


def client_ip(scope: Scope, headers: dict[str, str] | None = None) -> str:
    h = headers if headers is not None else headers_of(scope)
    for k in ("cf-connecting-ip", "x-real-ip"):
        if h.get(k):
            return h[k].strip()[:64]
    if h.get("x-forwarded-for"):
        return h["x-forwarded-for"].split(",")[0].strip()[:64]
    client = scope.get("client")
    return client[0] if client else "?"


def is_https(scope: Scope, headers: dict[str, str] | None = None) -> bool:
    h = headers if headers is not None else headers_of(scope)
    return scope.get("scheme") in ("https", "wss") or h.get("x-forwarded-proto", "").lower() == "https"


# ---------------------------------------------------------------------- tokens
class AccessTokens:
    """Cookie value = ``v1.<issued unix time>.<HMAC-SHA256>``, keyed by a hash of the access key:
    the key never travels back to the browser, and changing the key logs everybody out."""

    def __init__(self, key: str, max_age_s: float) -> None:
        self._mac_key = hashlib.sha256(b"extrahorizon-access-cookie|" + key.encode("utf-8")).digest()
        self._key_digest = hashlib.sha256(key.encode("utf-8")).digest()
        self.max_age_s = max_age_s

    def check_key(self, candidate: str) -> bool:
        return hmac.compare_digest(hashlib.sha256(candidate.encode("utf-8")).digest(), self._key_digest)

    def _sig(self, payload: str) -> str:
        mac = hmac.new(self._mac_key, payload.encode("ascii"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")

    def issue(self, now: float | None = None) -> str:
        payload = f"v1.{int(now if now is not None else time.time())}"
        return f"{payload}.{self._sig(payload)}"

    def valid(self, token: str | None, now: float | None = None) -> bool:
        if not token or token.count(".") != 2:
            return False
        version, issued, sig = token.split(".")
        if version != "v1" or not issued.isdigit():
            return False
        if not hmac.compare_digest(sig, self._sig(f"{version}.{issued}")):
            return False
        age = (now if now is not None else time.time()) - int(issued)
        return -60 <= age <= self.max_age_s


def cookie_token(headers: dict[str, str]) -> str | None:
    raw = headers.get("cookie")
    if not raw:
        return None
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except Exception:  # noqa: BLE001 — a malformed cookie header is just "no cookie"
        return None
    morsel = jar.get(COOKIE)
    return morsel.value if morsel else None


# ---------------------------------------------------------------------- brute-force brake
class LoginLimiter:
    """At most ``per_ip`` wrong keys per client and ``total`` overall within ``window_s``."""

    def __init__(self, per_ip: int = 8, total: int = 60, window_s: float = 600.0) -> None:
        self.per_ip, self.total, self.window_s = per_ip, total, window_s
        self._fails: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()

    def _prune(self, now: float) -> None:
        while self._all and now - self._all[0] > self.window_s:
            self._all.popleft()
        for ip in list(self._fails):
            q = self._fails[ip]
            while q and now - q[0] > self.window_s:
                q.popleft()
            if not q:
                del self._fails[ip]

    def retry_after(self, ip: str, now: float | None = None) -> float:
        """Seconds until this client may try again (0 = allowed now)."""
        now = time.monotonic() if now is None else now
        self._prune(now)
        waits = []
        q = self._fails.get(ip)
        if q and len(q) >= self.per_ip:
            waits.append(self.window_s - (now - q[0]))
        if len(self._all) >= self.total:
            waits.append(self.window_s - (now - self._all[0]))
        return max(waits, default=0.0)

    def failed(self, ip: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._fails.setdefault(ip, deque()).append(now)
        self._all.append(now)
        if len(self._fails) > 10_000:  # bounded memory
            self._prune(now)

    def succeeded(self, ip: str) -> None:
        self._fails.pop(ip, None)


# ---------------------------------------------------------------------- guard
class AccessGuard:
    """ASGI middleware: remote ``/api/*`` requests and WebSockets need a valid access cookie."""

    def __init__(self, app: ASGIApp, tokens: AccessTokens | None) -> None:
        self.app = app
        self.tokens = tokens

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api/") or path in OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        h = headers_of(scope)
        if transport(scope, h) == "local":
            await self.app(scope, receive, send)
            return
        if self.tokens is None:
            code, status, ws_code = "remote_disabled", 403, 4403
            message = "Remote access is disabled on this server (EH_ACCESS_KEY is not set)."
        elif self.tokens.valid(cookie_token(h)):
            await self.app(scope, receive, send)
            return
        else:
            code, status, ws_code = "access_required", 401, 4401
            message = "Enter the access key first."
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": ws_code})
            return
        await JSONResponse({"code": code, "message": message}, status_code=status)(scope, receive, send)
