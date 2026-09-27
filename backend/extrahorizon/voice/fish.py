"""Fish Audio live TTS over WebSocket (msgpack) + an offline mock.

Protocol (wss://api.fish.audio/v1/tts/live[/with-timestamp]):
  -> {"event":"start","request":{text:"", reference_id, format:"pcm", sample_rate, latency, ...}}
  -> {"event":"text","text":"..."}  … {"event":"flush"}  … {"event":"stop"}
  <- {"event":"audio","audio":<bytes>} … {"event":"finish","reason":"stop"} | {"event":"error",...}

* drama-3-preview exists ONLY on /v1/tts/live/with-timestamp — on /v1/tts/live an unknown
  model silently falls back to another voice model (documented in the owner's
  AzI notes, docs/drama3_voice.md); the model name goes in the ``model`` header.
* latency: a warm pool keeps a connected socket ready (TCP+TLS+WS ≈ 0.3-0.7 s here), the
  ``start`` event is sent as soon as a reply begins (the voice loads while the LLM writes
  its first words), format=pcm (no decoder), latency=balanced (drama: ~0.7 s to first audio).
* dead air: ``SilenceCap`` trims drama's long pauses; a watchdog ends a reply whose server
  went silent after flush/stop; a breaker stops redialing a failing service for a while.

Design adapted from AzI project.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from collections.abc import AsyncIterator
from typing import Any

import numpy as np

from .silence import SilenceCap

log = logging.getLogger("extrahorizon.tts")

_WSS = "wss://api.fish.audio"
_AUTH = (401, 402, 403)


class TtsError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def fish_url(settings: Any) -> str:
    if settings.fish_ws_url:
        return settings.fish_ws_url
    model = (settings.fish_model or "").lower()
    return _WSS + ("/v1/tts/live/with-timestamp" if model.startswith("drama") else "/v1/tts/live")


class TtsSession:
    """One spoken reply. ``audio()`` yields PCM s16le mono chunks until the reply ends."""

    failed: str = ""

    async def begin(self) -> None: ...
    async def send(self, text: str) -> None: ...
    async def finish(self) -> None: ...
    async def abort(self) -> None: ...
    def audio(self) -> AsyncIterator[bytes]: ...


class TtsEngine:
    provider = "none"
    configured = False

    async def warmup(self) -> None:
        return None

    async def open_session(self) -> TtsSession:
        raise TtsError("tts_unavailable", "Voice output is not configured.")

    def status(self) -> dict[str, Any]:
        return {"provider": self.provider, "configured": self.configured, "state": "off"}

    async def synthesize(self, text: str, timeout_s: float = 20.0) -> bytes:
        """Whole utterance (fillers): open, speak, collect."""
        session = await self.open_session()
        pcm = bytearray()

        async def collect() -> None:
            async for chunk in session.audio():
                pcm.extend(chunk)

        reader = asyncio.create_task(collect())
        try:
            await session.begin()
            await session.send(text)
            await session.finish()
            await asyncio.wait_for(reader, timeout_s)
        finally:
            reader.cancel()
            await session.abort()
        if session.failed:
            raise TtsError("tts_failed", session.failed)
        return bytes(pcm)

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------- Fish Audio
class FishSession(TtsSession):
    def __init__(self, ws: Any, settings: Any) -> None:
        self.ws = ws
        self.s = settings
        self.failed = ""
        self._q: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._started = False
        self._closed = False
        self._expect_since: float | None = None
        self._silence = SilenceCap(settings.tts_sample_rate, settings.tts_max_silence_ms, settings.tts_max_leading_silence_ms)
        self._io = asyncio.Lock()
        self.first_audio_at: float | None = None
        self.sent_at: float | None = None
        self._reader = asyncio.create_task(self._read())
        self._watch = asyncio.create_task(self._watchdog())

    async def _send(self, obj: dict[str, Any]) -> None:
        import ormsgpack

        await self.ws.send(ormsgpack.packb(obj))

    async def begin(self) -> None:
        async with self._io:
            if self._started or self._closed:
                return
            s = self.s
            req = {
                "text": "",
                "reference_id": s.fish_reference_id,
                "format": "pcm",
                "sample_rate": s.tts_sample_rate,
                "latency": s.fish_latency,
                "chunk_length": s.fish_chunk_length,
                "temperature": s.fish_temperature,
                "top_p": s.fish_top_p,
                "prosody": {"speed": s.fish_speed, "volume": s.fish_volume},
            }
            await self._send({"event": "start", "request": req})
            self._started = True

    async def send(self, text: str) -> None:
        if not text.strip() or self._closed:
            return
        await self.begin()
        async with self._io:
            try:
                await self._send({"event": "text", "text": text.strip() + " "})
                await self._send({"event": "flush"})
            except Exception as e:  # noqa: BLE001
                self._fail(f"send failed: {type(e).__name__}")
                return
            if self.sent_at is None:
                self.sent_at = time.monotonic()
            if self._expect_since is None:
                self._expect_since = time.monotonic()

    async def finish(self) -> None:
        if self._closed:
            return
        if not self._started:
            await self._q.put(None)  # nothing was said: end immediately
            self._closed = True
            return
        async with self._io:
            with contextlib.suppress(Exception):
                await self._send({"event": "stop"})
            if self._expect_since is None:
                self._expect_since = time.monotonic()

    async def abort(self) -> None:
        self._closed = True
        self._reader.cancel()
        self._watch.cancel()
        with contextlib.suppress(Exception):
            await self.ws.close()
        await self._q.put(None)

    def _fail(self, why: str) -> None:
        if not self.failed:
            self.failed = why
            log.warning("fish: %s", why)

    async def _read(self) -> None:
        import ormsgpack

        try:
            async for raw in self.ws:
                if isinstance(raw, str):
                    continue
                msg = ormsgpack.unpackb(raw)
                ev = msg.get("event")
                if ev == "audio":
                    pcm = msg.get("audio") or b""
                    if not pcm:
                        continue  # with-timestamp: alignment-only frame
                    self._expect_since = None
                    if self.first_audio_at is None:
                        self.first_audio_at = time.monotonic()
                    pcm = self._silence.feed(pcm)
                    if pcm:
                        await self._q.put(pcm)
                elif ev == "finish":
                    reason = str(msg.get("reason") or "")
                    if reason and reason != "stop":
                        self._fail(f"finish reason={reason}")
                    break
                elif ev == "error":
                    self._fail(f"error event: {str(msg.get('error') or msg)[:200]}")
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            if not self._closed:
                self._fail(f"connection lost: {type(e).__name__}")
        finally:
            self._closed = True
            self._watch.cancel()
            await self._q.put(None)
            with contextlib.suppress(Exception):
                await self.ws.close()
            if self._silence.trimmed_ms:
                log.info("fish: trimmed %d ms of model silence", self._silence.trimmed_ms)

    async def _watchdog(self) -> None:
        limit = float(self.s.fish_silence_timeout_s)
        try:
            while not self._closed:
                await asyncio.sleep(0.25)
                since = self._expect_since
                if since is not None and time.monotonic() - since > limit:
                    self._fail(f"server silent for {limit:.0f}s after text")
                    self._reader.cancel()
                    return
        except asyncio.CancelledError:
            pass

    async def audio(self) -> AsyncIterator[bytes]:
        while True:
            item = await self._q.get()
            if item is None:
                return
            yield item


class FishEngine(TtsEngine):
    provider = "fish"

    def __init__(self, settings: Any) -> None:
        self.s = settings
        key = settings.fish_api_key.get_secret_value().strip() if settings.fish_api_key else ""
        self._key = key
        self.configured = bool(key) and settings.tts_enabled
        self._warm: asyncio.Queue[Any] = asyncio.Queue()
        self._refill_task: asyncio.Task | None = None
        self._failures = 0
        self._breaker_until = 0.0
        self.last_error: str | None = None
        self.last_ttfa_ms: int | None = None

    def status(self) -> dict[str, Any]:
        state = "off" if not self.configured else "down" if time.monotonic() < self._breaker_until else (
            "degraded" if self._failures else "ok")
        return {
            "provider": "fish",
            "model": self.s.fish_model,
            "voice": self.s.fish_reference_id,
            "configured": self.configured,
            "state": state,
            "last_error": self.last_error,
            "warm": self._warm.qsize(),
        }

    async def _dial(self):
        from websockets.asyncio.client import connect

        now = time.monotonic()
        if now < self._breaker_until:
            raise TtsError("tts_unavailable", f"Fish Audio unavailable ({self.last_error}); retrying in {self._breaker_until - now:.0f}s")
        try:
            ws = await connect(
                fish_url(self.s),
                additional_headers={"Authorization": f"Bearer {self._key}", "model": self.s.fish_model},
                max_size=None,
                open_timeout=self.s.fish_connect_timeout_s,
                close_timeout=2,
                ping_interval=20,
            )
        except Exception as e:  # noqa: BLE001
            self._failures += 1
            status = getattr(getattr(e, "response", None), "status_code", None)
            self.last_error = f"HTTP {status}" if status else type(e).__name__
            if status in _AUTH or self._failures >= 3:
                self._breaker_until = time.monotonic() + 30.0
                log.error("Fish Audio unreachable (%s) — voice output paused for 30 s", self.last_error)
            raise TtsError("tts_unavailable", f"Could not connect to Fish Audio ({self.last_error}).") from e
        self._failures = 0
        self.last_error = None
        return ws

    async def _refill(self) -> None:
        try:
            while self._warm.qsize() < max(0, self.s.fish_warm_connections):
                self._warm.put_nowait(await self._dial())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — already logged/recorded
            pass

    def _schedule_refill(self) -> None:
        if self.configured and (self._refill_task is None or self._refill_task.done()):
            self._refill_task = asyncio.create_task(self._refill())

    async def warmup(self) -> None:
        if self.configured:
            await self._refill()

    async def open_session(self) -> TtsSession:
        if not self.configured:
            raise TtsError("tts_unavailable", "FISH_API_KEY is not set (.env).")
        from websockets.protocol import State

        ws = None
        while not self._warm.empty():
            cand = self._warm.get_nowait()
            if getattr(cand, "state", None) is State.OPEN:
                ws = cand
                break
            with contextlib.suppress(Exception):
                await cand.close()
        if ws is None:
            ws = await self._dial()
        self._schedule_refill()
        return FishSession(ws, self.s)

    async def aclose(self) -> None:
        if self._refill_task:
            self._refill_task.cancel()
        while not self._warm.empty():
            with contextlib.suppress(Exception):
                await self._warm.get_nowait().close()


# ---------------------------------------------------------------------- offline mock
class MockSession(TtsSession):
    """Deterministic "voice": a soft tone whose length follows the text (tests, offline)."""

    def __init__(self, sample_rate: int, ms_per_char: float = 45.0, delay_s: float = 0.02) -> None:
        self.sr = sample_rate
        self.ms_per_char = ms_per_char
        self.delay_s = delay_s
        self.failed = ""
        self._q: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self._lock = asyncio.Lock()
        self.texts: list[str] = []

    async def _produce(self, text: str) -> None:
        from .tags import strip_tags

        n = int(self.sr * min(4.0, max(0.2, len(strip_tags(text)) * self.ms_per_char / 1000)))
        t = np.arange(n) / self.sr
        tone = (np.sin(2 * math.pi * 220 * t) * 0.15 * 32767).astype("<i2").tobytes()
        step = int(self.sr * 0.1) * 2
        async with self._lock:
            for i in range(0, len(tone), step):
                await asyncio.sleep(self.delay_s)
                await self._q.put(tone[i : i + step])

    async def send(self, text: str) -> None:
        self.texts.append(text)
        self._tasks.append(asyncio.create_task(self._produce(text)))

    async def finish(self) -> None:
        producers = list(self._tasks)

        async def end() -> None:
            for t in producers:
                with contextlib.suppress(Exception):
                    await t
            await self._q.put(None)

        self._tasks.append(asyncio.create_task(end()))

    async def abort(self) -> None:
        for t in self._tasks:
            t.cancel()
        await self._q.put(None)

    async def audio(self) -> AsyncIterator[bytes]:
        while True:
            item = await self._q.get()
            if item is None:
                return
            yield item


class MockTts(TtsEngine):
    provider = "mock"
    configured = True

    def __init__(self, sample_rate: int = 44100, delay_s: float = 0.02) -> None:
        self.sr = sample_rate
        self.delay_s = delay_s
        self.sessions: list[MockSession] = []

    def status(self) -> dict[str, Any]:
        return {"provider": "mock", "model": "mock-tone", "configured": True, "state": "ok", "last_error": None}

    async def open_session(self) -> TtsSession:
        s = MockSession(self.sr, delay_s=self.delay_s)
        self.sessions.append(s)
        return s


def create_tts(settings: Any) -> TtsEngine:
    if not settings.tts_enabled:
        return TtsEngine()
    if settings.tts_provider == "mock":
        return MockTts(settings.tts_sample_rate)
    return FishEngine(settings)
