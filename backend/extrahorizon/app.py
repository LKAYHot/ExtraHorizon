"""FastAPI application: HTTP API, SSE chat, vision + voice WebSockets, static UI."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import secrets
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .access import (
    COOKIE,
    AccessGuard,
    AccessTokens,
    LoginLimiter,
    client_ip,
    cookie_token,
    headers_of,
    is_https,
    transport,
)
from .config import SILERO_VAD, Settings, get_settings
from .llm import BaseLLM, create_llm
from .live_ws import LiveConnection
from .sessions import ApiError, SessionStore
from .turns import TurnRunner
from .vision.model_fetch import ensure_asset
from .vision.service import VisionService
from .vision_ws import VisionConnection
from .voice.fillers import FillerBank
from .voice.fish import TtsEngine, create_tts
from .voice.stt import create_stt

log = logging.getLogger("extrahorizon")

SESSION_ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_SESSION_ID_RE = re.compile(SESSION_ID_PATTERN)


# ---------------------------------------------------------------------- schemas
class ChatRequest(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    message: str | None = Field(default=None, max_length=4000)
    subject: str | None = Field(default=None, max_length=40)
    analysis: bool = False  # run the utility-coordination analysis before answering


class AnalyzeRequest(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    refresh: bool = False  # read the county's data again instead of the cached copy
    distance_m: float | None = Field(default=None, ge=0, le=5000)
    window_days: int | None = Field(default=None, ge=0, le=3650)
    area_m: float | None = Field(default=None, gt=0, le=20000)


class RecheckRequest(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    finding_id: str = Field(pattern=r"^F\d{1,6}$")


class ResetRequest(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)


class AccessRequest(BaseModel):
    key: str = Field(min_length=1, max_length=256)


# ---------------------------------------------------------------------- helpers
def sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


@dataclass
class Services:
    """Process-wide providers shared by all sessions (swappable in tests)."""

    settings: Settings
    llm: BaseLLM
    tts: TtsEngine
    fillers: FillerBank
    vision: VisionService
    stt_factory: Any = None
    vad_factory: Any = None
    coord: Any = None  # utility-coordination analysis (coord/service.py)
    vad_ok: bool = False
    vad_reason: str | None = "starting"

    def make_stt(self):
        return (self.stt_factory or create_stt)(self.settings)

    def make_segmenter(self):
        from .voice.vad import SileroVad, VadSegmenter

        if self.vad_factory is not None:
            return self.vad_factory()
        return VadSegmenter(SileroVad(self.settings.vad_model_path), self.settings)


class OriginGuard:
    """Rejects cross-site requests: a random web page must not be able to drive the
    local tutor (spend the API keys), open the camera socket or the microphone socket."""

    def __init__(self, app: ASGIApp, allowed: set[str]) -> None:
        self.app = app
        self.allowed = allowed

    def _ok(self, origin: str, host: str | None) -> bool:
        if origin in self.allowed:
            return True
        return bool(host) and origin in (f"http://{host}", f"https://{host}")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
            origin = headers.get("origin")
            needs_check = scope["type"] == "websocket" or scope.get("method") not in ("GET", "HEAD", "OPTIONS")
            if origin and needs_check and not self._ok(origin, headers.get("host")):
                log.warning("blocked cross-origin %s from %s", scope["type"], origin)
                if scope["type"] == "websocket":
                    await receive()
                    await send({"type": "websocket.close", "code": 4003})
                    return
                resp = JSONResponse({"code": "forbidden_origin", "message": "Cross-origin request blocked."}, 403)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


class UIStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope):  # type: ignore[override]
        resp = await super().get_response(path, scope)
        if path.startswith("_app/immutable/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-cache"
        return resp


def _quiet_windows_disconnect_noise() -> None:
    """On Windows the Proactor loop logs a scary traceback (WinError 10022/10054) when a
    browser tab drops a socket abruptly. It is harmless; hide exactly that, keep the rest."""
    if sys.platform != "win32":
        return
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()

    def handler(lp: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        if isinstance(exc, (ConnectionResetError, OSError)) and getattr(exc, "winerror", None) in (10022, 10053, 10054):
            return
        if previous is not None:
            previous(lp, context)
        else:
            lp.default_exception_handler(context)

    loop.set_exception_handler(handler)


# ---------------------------------------------------------------------- app factory
def create_app(
    settings: Settings | None = None,
    *,
    llm: BaseLLM | None = None,
    vision: VisionService | None = None,
    tts: TtsEngine | None = None,
    stt_factory: Any = None,
    vad_factory: Any = None,
    coord: Any = None,
) -> FastAPI:
    settings = settings or get_settings()
    llm = llm or create_llm(settings)
    vision = vision or VisionService(settings)
    tts = tts if tts is not None else create_tts(settings)
    services = Services(settings, llm, tts, FillerBank(tts, settings), vision, stt_factory, vad_factory)
    if settings.coord_enabled:
        from .coord.service import CoordService

        services.coord = coord if coord is not None else CoordService(settings)
    store = SessionStore(settings)
    boot_id = secrets.token_hex(8)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _quiet_windows_disconnect_noise()
        await vision.startup()
        if vad_factory is not None:
            services.vad_ok, services.vad_reason = True, None
        else:
            loop = asyncio.get_running_loop()
            services.vad_ok, services.vad_reason = await loop.run_in_executor(
                None, lambda: ensure_asset(SILERO_VAD, settings.vad_model_path, allow_download=settings.vision_auto_download))

        async def voice_warmup() -> None:
            with contextlib.suppress(Exception):
                await tts.warmup()  # a connected Fish socket is waiting for the first reply
            services.fillers.start()  # synthesize/cache the filler clips in the background

        async def sweeper() -> None:
            while True:
                await asyncio.sleep(60)
                store.sweep()

        tasks = [asyncio.create_task(sweeper()), asyncio.create_task(voice_warmup())]
        log.info(
            "ExtraHorizon %s ready — LLM %s/%s (%s) · voice %s/%s (%s) · STT %s · vision %s",
            __version__, llm.provider, llm.model, "ok" if llm.configured else "NOT CONFIGURED",
            getattr(tts, "provider", "none"), settings.fish_model, "ok" if tts.configured else "off",
            settings.stt_model if settings.stt_configured else "off",
            "ready" if vision.available else f"unavailable ({vision.reason})",
        )
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            services.fillers.stop()
            for t in tasks:
                with contextlib.suppress(BaseException):
                    await t
            await llm.aclose()
            await tts.aclose()
            if services.coord is not None:
                await services.coord.aclose()
            vision.shutdown()

    app = FastAPI(
        title="ExtraHorizon", version=__version__, lifespan=lifespan, docs_url="/api/docs",
        redoc_url=None, swagger_ui_oauth2_redirect_url=None, openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.services = services
    app.state.store = store
    app.state.boot_id = boot_id

    port = settings.port
    dev_origins = {f"http://{h}:{p}" for h in ("127.0.0.1", "localhost", "[::1]") for p in (port, 5173, 4173)}
    allowed_origins = dev_origins | set(settings.allowed_origins)
    wildcard_bind = settings.host in ("0.0.0.0", "::")
    allowed_hosts = ["127.0.0.1", "localhost", "::1", "[::1]", "testserver", *settings.allowed_hosts]
    if settings.public_url:  # the remote demo's public name (e.g. behind Cloudflare Tunnel)
        allowed_origins.add(settings.public_url)
        allowed_hosts.append(urlsplit(settings.public_url).hostname or "")
    if not wildcard_bind:
        allowed_hosts.append(settings.host)
    elif not settings.allowed_hosts:
        log.warning("bound to %s but EH_ALLOWED_HOSTS is empty: requests from other machines will be rejected "
                    "(set EH_ALLOWED_HOSTS / EH_ALLOWED_ORIGINS explicitly; '*' is never used)", settings.host)
    tokens = (AccessTokens(settings.access_key.get_secret_value().strip(), settings.access_cookie_days * 86400)
              if settings.access_configured else None)
    limiter = LoginLimiter()
    if settings.public_url and tokens is None:
        log.warning("EH_PUBLIC_URL is set but EH_ACCESS_KEY is not: remote requests will be refused")
    app.add_middleware(AccessGuard, tokens=tokens)
    app.add_middleware(CORSMiddleware, allow_origins=sorted(allowed_origins), allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(OriginGuard, allowed=allowed_origins)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status)

    # ------------------------------------------------------------------ remote access
    def access_state(request: Request) -> dict[str, Any]:
        h = headers_of(request.scope)
        how = transport(request.scope, h)
        remote = how != "local"
        ok = not remote or (tokens is not None and tokens.valid(cookie_token(h)))
        return {"required": remote, "ok": ok, "configured": tokens is not None, "transport": how,
                "public_url": settings.public_url}

    @app.get("/api/access")
    async def access_status(request: Request) -> dict[str, Any]:
        return access_state(request)

    @app.post("/api/access")
    async def access_login(req: AccessRequest, request: Request, response: Response) -> dict[str, Any]:
        state = access_state(request)
        if not state["required"]:
            return {**state, "ok": True}
        if tokens is None:
            raise ApiError(403, "remote_disabled", "Remote access is disabled on this server (EH_ACCESS_KEY is not set).")
        ip = client_ip(request.scope)
        wait = limiter.retry_after(ip)
        if wait > 0:
            return JSONResponse({"code": "too_many_attempts", "message": "Too many wrong keys — try again later.",
                                 "retry_after_s": int(wait) + 1}, status_code=429,
                                headers={"Retry-After": str(int(wait) + 1)})
        if not tokens.check_key(req.key.strip()):
            limiter.failed(ip)
            log.warning("wrong access key from %s (%s)", ip, state["transport"])
            raise ApiError(401, "wrong_key", "That key is not right.")
        limiter.succeeded(ip)
        log.info("remote access granted to %s (%s)", ip, state["transport"])
        response.set_cookie(COOKIE, tokens.issue(), max_age=int(tokens.max_age_s), httponly=True,
                            secure=is_https(request.scope), samesite="strict", path="/")
        return {**state, "ok": True}

    @app.delete("/api/access")
    async def access_logout(request: Request, response: Response) -> dict[str, Any]:
        response.delete_cookie(COOKIE, path="/", secure=is_https(request.scope), httponly=True, samesite="strict")
        return {**access_state(request), "ok": False}

    # ------------------------------------------------------------------ routes
    @app.get("/api/health")
    async def health(request: Request, deep: bool = False) -> dict[str, Any]:
        llm_status = llm.status()
        if deep and llm.configured:
            llm_status["reachable"] = await llm.ping()
        return {
            "status": "ok",
            "boot_id": boot_id,
            "version": __version__,
            "persona": settings.persona_name,
            "llm": llm_status,
            "vision": vision.status(),
            "emotion": settings.public_emotion_config(),
            "tts": tts.status(),
            "stt": {"provider": settings.stt_provider, "model": settings.stt_model,
                    "configured": settings.stt_configured, "vad": services.vad_ok, "vad_reason": services.vad_reason},
            "fillers": services.fillers.state,
            "coord": {"enabled": services.coord is not None,
                      "offline": bool(services.coord is not None and services.coord.offline)},
            "sessions": len(store),
            "client": {"transport": transport(request.scope)},
        }

    @app.post("/api/session/reset")
    async def reset_session(req: ResetRequest) -> dict[str, Any]:
        epoch = store.get_or_create(req.session_id).reset()
        return {"ok": True, "epoch": epoch, "boot_id": boot_id}

    @app.post("/api/session/interrupt")
    async def interrupt_session(req: ResetRequest) -> dict[str, Any]:
        """Stop button without the voice socket: stop the answer in flight (kept, marked
        interrupted) and the voice."""
        session = store.get(req.session_id)
        stopped = False
        if session is not None:
            live = session.live_conn
            stopped = live.interrupt("button") if live is not None else session.interrupt("interrupted")
        return {"ok": True, "stopped": stopped}

    @app.get("/api/session/{session_id}/state")
    async def session_state(session_id: str) -> dict[str, Any]:
        if not _SESSION_ID_RE.match(session_id):
            raise ApiError(422, "bad_session_id", "Invalid session id.")
        return store.get_or_create(session_id).state_payload(boot_id)

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> StreamingResponse:
        session = store.get_or_create(req.session_id)
        plan = session.plan_chat(message=req.message, subject=req.subject, source="text", analysis=req.analysis)
        log.info("chat %s session=%s… chars=%d", plan.request_id, session.id[:8], len(plan.user_msg["text"]))
        # typed questions are answered in text over SSE and, if the voice socket is open,
        # spoken through it as well
        runner = TurnRunner(session, plan, llm, settings, tts, session.live_conn, coord=services.coord)

        async def stream() -> AsyncIterator[bytes]:
            async for name, data in runner.events():
                if name == "discarded":
                    return
                yield sse(name, data)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------------ utility-coordination analysis
    def coord_service():
        if services.coord is None:
            raise ApiError(404, "analysis_disabled", "The utility-coordination analysis is turned off (EH_COORD_ENABLED).")
        return services.coord

    @app.get("/api/coord/catalog")
    async def coord_catalog() -> dict[str, Any]:
        from .coord.catalog import CONFLICTS, PUBLISHER, REGION, SOURCES

        svc = coord_service()
        return {
            "region": REGION["name"], "publisher": PUBLISHER, "status": svc.status(),
            "sources": [{"key": s.key, "title": s.title, "kind": s.kind, "utility": s.utility, "url": s.url,
                         "item_url": s.item_url} for s in SOURCES],
            "conflicts": {"key": CONFLICTS.key, "title": CONFLICTS.title, "url": CONFLICTS.url,
                          "item_url": CONFLICTS.item_url},
            "defaults": {"distance_m": settings.coord_distance_m, "window_days": settings.coord_window_days,
                         "area_m": settings.coord_area_m},
        }

    @app.post("/api/coord/analyze")
    async def coord_analyze(req: AnalyzeRequest) -> dict[str, Any]:
        from .coord.arcgis import SourceError
        from .coord.service import public_report

        svc = coord_service()
        session = store.get_or_create(req.session_id)
        rules = {**session.coord_params}
        for k in ("distance_m", "window_days", "area_m"):
            v = getattr(req, k)
            if v is not None:
                rules[k] = v
        epoch = session.epoch
        try:
            report = await svc.analyze(svc.params(rules), refresh=req.refresh)
        except SourceError as e:
            raise ApiError(502, "analysis_source", f"The county's data could not be read: {e.message}") from e
        if session.epoch != epoch:  # "New session" while it ran: the old session's analysis is gone
            raise ApiError(409, "session_reset", "The session was reset while the analysis ran.")
        session.coord_params = rules  # remembered only once they produced an analysis
        session.analysis = report
        return public_report(report)

    @app.get("/api/coord/report")
    async def coord_report(session_id: str) -> dict[str, Any]:
        from .coord.service import public_report

        if not _SESSION_ID_RE.match(session_id):
            raise ApiError(422, "bad_session_id", "Invalid session id.")
        session = store.get(session_id)
        if session is None or session.analysis is None:
            raise ApiError(404, "no_analysis", "No analysis in this session yet.")
        return public_report(session.analysis)

    @app.get("/api/coord/finding")
    async def coord_finding(session_id: str, id: str) -> dict[str, Any]:  # noqa: A002 — the query parameter
        """One finding of the analysis on screen — also one the panel does not list (a click on "F450")."""
        from .coord.report import all_findings

        if not _SESSION_ID_RE.match(session_id) or not re.fullmatch(r"F\d{1,6}", id):
            raise ApiError(422, "bad_request", "Invalid session id or finding id.")
        session = store.get(session_id)
        if session is None or session.analysis is None:
            raise ApiError(404, "no_analysis", "No analysis in this session yet.")
        f = next((x for x in all_findings(session.analysis) if x["id"] == id), None)
        if f is None:
            raise ApiError(404, "no_finding", f"No finding {id} in this analysis.")
        return f

    @app.delete("/api/coord/report")
    async def coord_close(session_id: str) -> dict[str, Any]:
        if not _SESSION_ID_RE.match(session_id):
            raise ApiError(422, "bad_session_id", "Invalid session id.")
        session = store.get(session_id)
        if session is not None:
            session.analysis = None
        return {"ok": True}

    @app.post("/api/coord/recheck")
    async def coord_recheck(req: RecheckRequest) -> dict[str, Any]:
        """Read both projects of a finding again from the county's service now and compare."""
        svc = coord_service()
        session = store.get(req.session_id)
        if session is None or session.analysis is None:
            raise ApiError(404, "no_analysis", "No analysis in this session yet.")
        try:
            return await svc.recheck(session.analysis, req.finding_id)
        except KeyError as e:
            raise ApiError(404, "no_finding", f"No finding {req.finding_id} in this analysis.") from e

    @app.websocket("/api/vision")
    async def vision_socket(ws: WebSocket) -> None:
        sid = ws.query_params.get("session_id", "")
        if not _SESSION_ID_RE.match(sid):
            await ws.close(code=4002)
            return
        await ws.accept()
        await VisionConnection(ws, store.get_or_create(sid), vision, settings, boot_id).run()

    @app.websocket("/api/live")
    async def live_socket(ws: WebSocket) -> None:
        sid = ws.query_params.get("session_id", "")
        if not _SESSION_ID_RE.match(sid):
            await ws.close(code=4002)
            return
        await ws.accept()
        await LiveConnection(ws, store.get_or_create(sid), services, settings, boot_id).run()

    # ------------------------------------------------------------------ UI
    static_dir = settings.static_dir
    if (static_dir / "index.html").exists():
        app.mount("/", UIStaticFiles(directory=static_dir, html=True), name="ui")
    else:

        @app.get("/", response_class=HTMLResponse)
        async def no_ui() -> str:
            return (
                "<!doctype html><meta charset=utf-8><title>ExtraHorizon API</title>"
                "<body style='font-family:system-ui;background:#0a1020;color:#dfe6ff;padding:40px'>"
                "<h1>ExtraHorizon backend is running</h1><p>The UI is not built yet. Run "
                "<code>npm run build</code> in <code>frontend/</code> (then reload), or use the dev "
                "server: <code>npm run dev</code> → http://127.0.0.1:5173</p>"
                "<p><a style='color:#9db4ff' href='/api/health'>/api/health</a></p></body>"
            )

    return app
