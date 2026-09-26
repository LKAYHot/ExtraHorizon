"""FastAPI application: HTTP API, SSE chat streaming, vision WebSocket, static UI."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import secrets
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import anyio
from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .config import Settings, get_settings
from .llm import BaseLLM, LLMError, StreamInfo, create_llm, map_openai_error
from .sessions import ApiError, ChatCancelled, ChatPlan, Session, SessionStore
from .vision.service import VisionService
from .vision_ws import VisionConnection

log = logging.getLogger("extrahorizon")

SESSION_ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_SESSION_ID_RE = re.compile(SESSION_ID_PATTERN)


# ---------------------------------------------------------------------- schemas
class ChatRequest(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    mode: Literal["normal", "explain_differently"] = "normal"
    message: str | None = Field(default=None, max_length=4000)
    event_id: str | None = Field(default=None, max_length=40)
    subject: str | None = Field(default=None, max_length=40)


class ResetRequest(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)


# ---------------------------------------------------------------------- helpers
def sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


_END = object()


async def _next_or_cancel(agen: AsyncIterator[str], timeout: float, cancel: asyncio.Event) -> tuple[str, Any]:
    """Next chunk, or 'end' / 'cancel' / 'timeout' — whichever comes first."""
    if cancel.is_set():
        return "cancel", None
    nxt = asyncio.ensure_future(agen.__anext__())
    stop = asyncio.ensure_future(cancel.wait())
    try:
        done, _ = await asyncio.wait({nxt, stop}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    except BaseException:
        nxt.cancel()
        stop.cancel()
        raise
    stop.cancel()
    if nxt in done:
        try:
            return "chunk", nxt.result()
        except StopAsyncIteration:
            return "end", None
    nxt.cancel()
    with contextlib.suppress(BaseException):
        await nxt  # let the provider stream unwind (closes the HTTP response)
    return ("cancel", None) if stop in done else ("timeout", None)


class OriginGuard:
    """Rejects cross-site requests: a random web page must not be able to drive the
    local tutor (spend the API key) or open the camera socket."""

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
) -> FastAPI:
    settings = settings or get_settings()
    llm = llm or create_llm(settings)
    vision = vision or VisionService(settings)
    store = SessionStore(settings)
    boot_id = secrets.token_hex(8)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _quiet_windows_disconnect_noise()
        await vision.startup()
        async def sweeper() -> None:
            while True:
                await asyncio.sleep(60)
                store.sweep()
        task = asyncio.create_task(sweeper())
        log.info(
            "ExtraHorizon %s ready — LLM: %s/%s (%s), vision: %s",
            __version__,
            llm.provider,
            llm.model,
            "configured" if llm.configured else "NOT CONFIGURED",
            "ready" if vision.available else f"unavailable ({vision.reason})",
        )
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
            await llm.aclose()
            vision.shutdown()

    app = FastAPI(
        title="ExtraHorizon",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.llm = llm
    app.state.vision = vision
    app.state.store = store
    app.state.boot_id = boot_id

    port = settings.port
    dev_origins = {
        f"http://{h}:{p}" for h in ("127.0.0.1", "localhost", "[::1]") for p in (port, 5173, 4173)
    }
    allowed_origins = dev_origins | set(settings.allowed_origins)
    wildcard_bind = settings.host in ("0.0.0.0", "::")
    allowed_hosts = ["127.0.0.1", "localhost", "::1", "[::1]", "testserver", *settings.allowed_hosts]
    if not wildcard_bind:
        allowed_hosts.append(settings.host)
    elif not settings.allowed_hosts:
        log.warning(
            "bound to %s but EH_ALLOWED_HOSTS is empty: requests from other machines will be rejected "
            "(set EH_ALLOWED_HOSTS / EH_ALLOWED_ORIGINS explicitly; '*' is never used)", settings.host
        )
    app.add_middleware(CORSMiddleware, allow_origins=sorted(allowed_origins), allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(OriginGuard, allowed=allowed_origins)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status)

    # ------------------------------------------------------------------ routes
    @app.get("/api/health")
    async def health(deep: bool = False) -> dict[str, Any]:
        llm_status = llm.status()
        if deep and llm.configured:
            llm_status["reachable"] = await llm.ping()
        return {
            "status": "ok",
            "boot_id": boot_id,
            "version": __version__,
            "llm": llm_status,
            "vision": vision.status(),
            "engine": settings.public_engine_config(),
            "sessions": len(store),
        }

    @app.post("/api/session/reset")
    async def reset_session(req: ResetRequest) -> dict[str, Any]:
        epoch = store.get_or_create(req.session_id).reset()
        return {"ok": True, "epoch": epoch, "boot_id": boot_id}

    @app.get("/api/session/{session_id}/state")
    async def session_state(session_id: str) -> dict[str, Any]:
        if not _SESSION_ID_RE.match(session_id):
            raise ApiError(422, "bad_session_id", "Invalid session id.")
        return store.get_or_create(session_id).state_payload(boot_id)

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> StreamingResponse:
        session = store.get_or_create(req.session_id)
        plan = session.plan_chat(mode=req.mode, message=req.message, event_id=req.event_id, subject=req.subject)
        log.info(
            "chat %s session=%s… mode=%s chars=%d", plan.request_id, session.id[:8], plan.mode, len(plan.user_msg["text"])
        )
        return StreamingResponse(
            _chat_stream(session, plan, llm, settings),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.websocket("/api/vision")
    async def vision_socket(ws: WebSocket) -> None:
        sid = ws.query_params.get("session_id", "")
        if not _SESSION_ID_RE.match(sid):
            await ws.close(code=4002)
            return
        await ws.accept()
        session = store.get_or_create(sid)
        await VisionConnection(ws, session, vision, settings, boot_id).run()

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


async def _chat_stream(session: Session, plan: ChatPlan, llm: BaseLLM, settings: Settings) -> AsyncIterator[bytes]:
    t0 = time.monotonic()
    committed = False
    yield sse("meta", plan.meta(llm.model))
    if not llm.configured:
        err = LLMError(
            "llm_not_configured",
            "OPENAI_API_KEY is not set on the server. Put it in .env and restart the backend.",
            False,
        )
        llm.note_error(err)
        session.abort_chat(plan)
        yield sse("error", err.public())
        return

    agen = llm.stream(plan.llm_messages)
    parts: list[str] = []
    ttft: float | None = None
    info = StreamInfo(model=llm.model)
    reported = False  # an error event was sent to the client
    try:
        while True:
            budget = t0 + settings.llm_total_timeout_s - time.monotonic()
            step = settings.llm_first_token_timeout_s if ttft is None else settings.llm_idle_timeout_s
            timeout = min(step, budget)
            if timeout <= 0:
                raise LLMError("llm_timeout", "The answer took too long. Retry.", True)
            kind, chunk = await _next_or_cancel(agen, timeout, plan.cancel)
            if kind == "end":
                break
            if kind == "cancel":
                raise ChatCancelled(plan.cancel_reason[-1] if plan.cancel_reason else "superseded")
            if kind == "timeout":
                raise LLMError(
                    "llm_timeout",
                    "The model did not start answering in time. Retry." if ttft is None else "The answer stalled. Retry.",
                    True,
                )
            if isinstance(chunk, StreamInfo):
                info = chunk
                continue
            if chunk:
                if ttft is None:
                    ttft = time.monotonic() - t0
                parts.append(chunk)
                yield sse("delta", {"text": chunk})
        text = "".join(parts).strip()
        if not text:
            raise LLMError("llm_empty", "The model returned an empty answer. Retry.", True)
        done = session.commit_chat(
            plan,
            text,
            model=info.model,
            ttft_ms=None if ttft is None else int(ttft * 1000),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            finish_reason=info.finish_reason,
        )
        committed = True
        llm.note_ok()
        log.info("chat %s done ttft=%sms elapsed=%sms", plan.request_id, done["ttft_ms"], done["elapsed_ms"])
        yield sse("done", done)
    except ChatCancelled as c:
        msg = "The session was reset." if c.code == "reset" else "A newer request replaced this one."
        reported = True
        log.info("chat %s cancelled: %s", plan.request_id, c.code)
        yield sse("error", {"code": c.code, "message": msg, "retryable": c.code != "reset"})
    except Exception as e:  # noqa: BLE001 — every failure ends the stream with a clear error
        err = e if isinstance(e, LLMError) else map_openai_error(e)
        llm.note_error(err)
        reported = True
        log.warning("chat %s failed: %s", plan.request_id, err.code)
        yield sse("error", err.public())
    finally:
        if not committed:
            session.abort_chat(plan)
            if not reported:
                log.info("chat %s stopped by the client (disconnect) — upstream stream closed, nothing committed", plan.request_id)
        with anyio.CancelScope(shield=True):
            with contextlib.suppress(BaseException):
                await agen.aclose()  # type: ignore[attr-defined]
