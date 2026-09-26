"""WebSocket ``/api/vision``: camera frames in, engine ticks/events out.

* Receiver: stores only the *latest* frame (older pending frames are dropped —
  the pipeline never builds a backlog, latency stays one frame).
* Processor: analyses frames in the vision thread pool, then ingests the result
  into the session (proxy → engine) on the event loop.
* Sender: the single writer of the socket, fed through a bounded queue, so chat
  commits / resets can notify this socket from anywhere without races.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import struct
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from .sessions import Session, now_ms
from .vision.service import VisionService

log = logging.getLogger("extrahorizon.vision")

LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    return host in LOOPBACK or host.startswith("127.") or host == "::ffff:127.0.0.1"


class VisionConnection:
    def __init__(self, ws: WebSocket, session: Session, vision: VisionService, settings: Any, boot_id: str) -> None:
        self.ws = ws
        self.session = session
        self.vision = vision
        self.settings = settings
        self.boot_id = boot_id
        self.out: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=512)
        self._pending: tuple[int, bytes] | None = None
        self._frame_ready = asyncio.Event()
        self._analyzer = None
        self._analyzer_failed = False
        self._has_slot = False
        self._closed = False
        self._last_frame_at = 0.0
        self.dropped = 0

    # ------------------------------------------------------------------ outbound
    def send(self, msg: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            self.out.put_nowait(msg)
        except asyncio.QueueFull:
            # the client is not reading; drop the oldest message (ticks are disposable)
            with contextlib.suppress(asyncio.QueueEmpty):
                self.out.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                self.out.put_nowait(msg)

    def supersede(self) -> None:
        self.send({"type": "superseded"})
        self.send(None)  # sender closes the socket after flushing

    async def _sender(self) -> None:
        try:
            while True:
                msg = await self.out.get()
                if msg is None:
                    await self.ws.close(code=4001)
                    return
                await self.ws.send_text(json.dumps(msg, separators=(",", ":")))
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            return

    # ------------------------------------------------------------------ lifecycle
    async def run(self) -> None:
        prev = self.session.attach_vision(self)
        if prev is not None and prev is not self:
            prev.supersede()
        client_host = self.ws.client.host if self.ws.client else None
        self.send(
            {
                "type": "hello",
                "session_id": self.session.id,
                "boot_id": self.boot_id,
                "server_time": now_ms(),
                "client_is_loopback": is_loopback(client_host),
                "vision": self.vision.status(),
                "config": self.settings.public_vision_config(),
            }
        )
        self.send(self.session.snapshot_message())
        sender = asyncio.create_task(self._sender(), name="eh-vision-sender")
        processor = asyncio.create_task(self._processor(), name="eh-vision-processor")
        try:
            await self._receiver()
        finally:
            self._closed = True
            self.session.detach_vision(self)
            if self.session.vision_conn is None:  # not replaced by a newer socket of this session
                self.session.vision_disconnected(time.monotonic(), now_ms())
            for task in (processor, sender):
                task.cancel()
            for task in (processor, sender):
                with contextlib.suppress(BaseException):
                    await task
            await self._release_analyzer()

    async def _release_analyzer(self) -> None:
        analyzer, self._analyzer = self._analyzer, None
        if analyzer is not None:
            loop = asyncio.get_running_loop()
            with contextlib.suppress(Exception):
                await loop.run_in_executor(self.vision.executor, analyzer.close)
        if self._has_slot:
            self._has_slot = False
            self.vision.release_slot()

    # ------------------------------------------------------------------ inbound
    async def _receiver(self) -> None:
        s = self.settings
        while True:
            try:
                msg = await self.ws.receive()
            except (WebSocketDisconnect, RuntimeError):
                return
            if msg.get("type") == "websocket.disconnect":
                return
            data = msg.get("bytes")
            if data is not None:
                if len(data) > s.max_frame_bytes + 4:
                    self.send({"type": "error", "code": "frame_too_large", "message": "Frame exceeds the size limit."})
                    continue
                if len(data) < 8:
                    self.send({"type": "error", "code": "bad_frame", "message": "Frame is too short."})
                    continue
                seq = struct.unpack(">I", data[:4])[0]
                if self._pending is not None:
                    self.dropped += 1
                self._pending = (seq, data[4:])
                self._frame_ready.set()
                self.session.touch()
                continue
            text = msg.get("text")
            if text is not None:
                self._handle_text(text)

    def _handle_text(self, text: str) -> None:
        try:
            m = json.loads(text)
            kind = m.get("type")
        except (ValueError, AttributeError):
            self.send({"type": "error", "code": "bad_message", "message": "Invalid JSON."})
            return
        t, t_ms = time.monotonic(), now_ms()
        sess = self.session
        if kind == "ping":
            self.send({"type": "pong", "t": m.get("t")})
        elif kind == "camera":
            status = str(m.get("status", ""))[:20]
            for out in sess.camera_status(status, t, t_ms):
                self.send(out)
        elif kind == "sim":
            if m.get("enabled") is False:
                outs = sess.set_sim(False, t, t_ms)
            else:
                try:
                    value = float(m.get("value", 0.0))
                except (TypeError, ValueError):
                    value = 0.0
                outs = sess.set_sim(True, t, t_ms) + sess.ingest_sim(value, t, t_ms)
            for out in outs:
                self.send(out)
        elif kind == "calibrate":
            sess.recalibrate()
            self.send({"type": "calibrating"})
        else:
            self.send({"type": "error", "code": "bad_message", "message": f"Unknown message type {kind!r}."})

    # ------------------------------------------------------------------ processing
    async def _ensure_analyzer(self) -> bool:
        if self._analyzer is not None:
            return True
        if self._analyzer_failed:
            return False
        if not self.vision.available:
            self._analyzer_failed = True
            self.send(
                {
                    "type": "error",
                    "code": "vision_unavailable",
                    "message": f"Vision processing is unavailable ({self.vision.reason}). Chat still works.",
                }
            )
            return False
        if not await self.vision.acquire_slot():
            self.send(
                {
                    "type": "error",
                    "code": "vision_busy",
                    "message": "Too many camera sessions on this backend. Close another tab.",
                }
            )
            self._analyzer_failed = True
            return False
        self._has_slot = True
        loop = asyncio.get_running_loop()
        try:
            self._analyzer = await loop.run_in_executor(self.vision.executor, self.vision.create_analyzer)
            return True
        except Exception as e:  # noqa: BLE001
            log.exception("failed to create face analyzer")
            self._analyzer_failed = True
            self.vision.release_slot()
            self._has_slot = False
            self.send({"type": "error", "code": "vision_unavailable", "message": f"Vision failed: {type(e).__name__}"})
            return False

    async def _processor(self) -> None:
        loop = asyncio.get_running_loop()
        min_interval = 1.0 / max(1.0, self.settings.max_fps)
        while True:
            await self._frame_ready.wait()
            self._frame_ready.clear()
            item, self._pending = self._pending, None
            if item is None:
                continue
            seq, jpeg = item
            if not await self._ensure_analyzer():
                # still acknowledge so the client does not stall; engine sees "unknown"
                t, t_ms = time.monotonic(), now_ms()
                for out in self.session.camera_status("vision_unavailable", t, t_ms) or [
                    {"type": "tick", "seq": seq, "t": t_ms, "vision": None, "engine": None}
                ]:
                    out = dict(out)
                    if out.get("type") == "tick":
                        out["seq"] = seq
                    self.send(out)
                continue
            # server-side rate cap (the client already paces itself)
            wait = self._last_frame_at + min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
                if self._pending is not None:  # a newer frame arrived meanwhile — use it
                    self.dropped += 1
                    seq, jpeg = self._pending
                    self._pending = None
            self._last_frame_at = time.monotonic()
            analyzer = self._analyzer
            frame = await loop.run_in_executor(self.vision.executor, analyzer.analyze_jpeg, jpeg)
            for out in self.session.ingest_frame(seq, frame, time.monotonic(), now_ms()):
                self.send(out)
