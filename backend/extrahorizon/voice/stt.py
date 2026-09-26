"""Realtime speech-to-text: OpenAI ``gpt-live-transcribe`` over WebSocket + an offline mock.

Chosen by measurement (noisy speech, SNR ≈ 5 dB, EN + RU, streamed in real time):
gpt-live-transcribe streams text *while you speak* (first words ≈1.3 s after onset) and
its final transcript arrives ≈0.4 s after ``commit`` (≈0.84 s after the end of speech
including our 0.4-0.55 s end-of-speech wait); gpt-4o-transcribe/-mini with server VAD
were exact too but gave no partials and finals 0.75-1.16 s after speech.
gpt-live-transcribe has no server VAD, so turn-taking is ours (local Silero VAD, see
vad.py): audio is only sent while an utterance is open (+ pre-roll), then committed.
That also keeps silence/noise away from the model and cuts cost.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger("extrahorizon.stt")

URL = "wss://api.openai.com/v1/realtime?intent=transcription"


class SttError(Exception):
    pass


class SttClient:
    """Callbacks: on_partial(utt_id, text), on_final(utt_id, text), on_error(message)."""

    provider = "none"

    def __init__(self) -> None:
        self.on_partial: Callable[[int, str], None] = lambda u, t: None
        self.on_final: Callable[[int, str], None] = lambda u, t: None
        self.on_error: Callable[[str], None] = lambda m: None

    async def start(self) -> None: ...
    async def set_context(self, said: str) -> None: ...
    async def append(self, utt: int, pcm24: bytes) -> None: ...
    async def commit(self, utt: int) -> None: ...
    async def cancel(self, utt: int) -> None: ...
    async def close(self) -> None: ...


class OpenAIRealtimeStt(SttClient):
    provider = "openai"

    def __init__(self, settings: Any) -> None:
        super().__init__()
        self.s = settings
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._item_to_utt: dict[str, int] = {}
        self._text: dict[int, str] = {}
        self._open_utt: int | None = None
        self._pending_commit: list[int] = []  # committed utterances waiting for their item id
        self._prompt = settings.stt_prompt
        self._reconnect: asyncio.Task | None = None
        self._retry_at = 0.0
        self._backoff = 1.0
        self._closed = False
        self.connected_at: float | None = None

    def _session(self) -> dict[str, Any]:
        s = self.s
        transcription: dict[str, Any] = {"model": s.stt_model}
        if s.stt_language:
            transcription["language"] = s.stt_language
        if self._prompt:
            transcription["prompt"] = self._prompt
        audio_in: dict[str, Any] = {
            "format": {"type": "audio/pcm", "rate": 24000},
            "transcription": transcription,
            "turn_detection": None,
        }
        if s.stt_noise_reduction != "off":
            audio_in["noise_reduction"] = {"type": s.stt_noise_reduction}
        return {"type": "session.update", "session": {"type": "transcription", "audio": {"input": audio_in}}}

    async def start(self) -> None:
        async with self._lock:
            if self._ws is not None:
                return
            from websockets.asyncio.client import connect

            key = self.s.openai_api_key.get_secret_value().strip() if self.s.openai_api_key else ""
            if not key:
                raise SttError("OPENAI_API_KEY is not set (.env).")
            try:
                self._ws = await connect(URL, additional_headers={"Authorization": f"Bearer {key}"},
                                         max_size=2**24, open_timeout=8, close_timeout=2, ping_interval=20)
                await self._ws.send(json.dumps(self._session()))
            except Exception as e:  # noqa: BLE001
                self._ws = None
                raise SttError(f"Could not connect to the transcription service ({type(e).__name__}).") from e
            self.connected_at = time.monotonic()
            self._backoff = 1.0
            self._reader = asyncio.create_task(self._read())

    def _kick_reconnect(self) -> None:
        """Reconnect in the background with back-off — never inside the audio path (a dead
        endpoint must not stall the live socket that also carries Stop and barge-in)."""
        if self._closed or time.monotonic() < self._retry_at:
            return
        if self._reconnect is not None and not self._reconnect.done():
            return

        async def run() -> None:
            try:
                await self.start()
            except Exception as e:  # noqa: BLE001
                self._retry_at = time.monotonic() + self._backoff
                self._backoff = min(15.0, self._backoff * 2)
                self.on_error(str(e)[:200])

        self._reconnect = asyncio.create_task(run())

    async def _send(self, obj: dict[str, Any]) -> bool:
        ws = self._ws
        if ws is None:
            self._kick_reconnect()
            return False  # dropped while the service is unreachable
        try:
            await ws.send(json.dumps(obj))
            return True
        except Exception:  # noqa: BLE001
            await self._reset()
            self._kick_reconnect()
            return False

    async def set_context(self, said: str) -> None:
        """Bias recognition toward the conversation: the tutor's last words go into the
        transcription prompt (a learner repeating "base case" / "memoization" is then
        heard right even in noise). Sent between utterances, only when it changed."""
        said = " ".join(said.split())[-240:]
        prompt = f"{self.s.stt_prompt} The tutor just said: {said}" if said else self.s.stt_prompt
        if prompt == self._prompt:
            return
        self._prompt = prompt
        if self._ws is not None:
            await self._send(self._session())

    async def append(self, utt: int, pcm24: bytes) -> None:
        if self._open_utt != utt:
            self._open_utt = utt
            self._text[utt] = ""
        await self._send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm24).decode()})

    async def commit(self, utt: int) -> None:
        self._pending_commit.append(utt)
        if self._open_utt == utt:
            self._open_utt = None
        if not await self._send({"type": "input_audio_buffer.commit"}):
            self._pending_commit.remove(utt)  # no final will come: answer with what was heard
            self.on_final(utt, self._text.pop(utt, ""))

    async def cancel(self, utt: int) -> None:
        if self._open_utt == utt:
            self._open_utt = None
            with contextlib.suppress(Exception):
                await self._send({"type": "input_audio_buffer.clear"})

    def _utt_for(self, item_id: str | None) -> int | None:
        if item_id is None:
            return self._open_utt or (self._pending_commit[0] if self._pending_commit else None)
        if item_id not in self._item_to_utt:
            utt = self._open_utt if self._open_utt is not None else (self._pending_commit[0] if self._pending_commit else None)
            if utt is None:
                return None
            self._item_to_utt[item_id] = utt
        return self._item_to_utt[item_id]

    async def _read(self) -> None:
        ws = self._ws
        try:
            async for raw in ws:  # type: ignore[union-attr]
                m = json.loads(raw)
                typ = m.get("type", "")
                if typ == "input_audio_buffer.committed":
                    item = m.get("item_id")
                    if self._pending_commit and item and item not in self._item_to_utt:
                        self._item_to_utt[item] = self._pending_commit[0]
                elif typ.endswith("input_audio_transcription.delta"):
                    utt = self._utt_for(m.get("item_id"))
                    if utt is not None:
                        self._text[utt] = self._text.get(utt, "") + (m.get("delta") or "")
                        self.on_partial(utt, self._text[utt])
                elif typ.endswith("input_audio_transcription.completed"):
                    utt = self._utt_for(m.get("item_id"))
                    if utt is not None:
                        if utt in self._pending_commit:
                            self._pending_commit.remove(utt)
                        text = (m.get("transcript") or self._text.get(utt, "")).strip()
                        self._text.pop(utt, None)
                        self.on_final(utt, text)
                elif typ.endswith("input_audio_transcription.failed") or typ == "error":
                    err = m.get("error") or {}
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    log.warning("stt error: %s", str(msg)[:200])
                    if typ != "error":
                        utt = self._utt_for(m.get("item_id"))
                        if utt is not None:
                            if utt in self._pending_commit:
                                self._pending_commit.remove(utt)
                            self.on_final(utt, "")
                    self.on_error(str(msg)[:200])
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("stt connection lost: %s", type(e).__name__)
        finally:
            if self._ws is ws:
                self._ws = None
                self._flush_pending()

    def _flush_pending(self) -> None:
        """The connection is gone: utterances committed on it get no transcript any more —
        finish them with their live text, and forget the item mapping (a new connection
        numbers its items afresh; a stale entry would shift every later transcript)."""
        pending, self._pending_commit = self._pending_commit, []
        self._item_to_utt.clear()
        self._open_utt = None
        for utt in pending:
            self.on_final(utt, self._text.pop(utt, ""))

    async def _reset(self) -> None:
        ws, self._ws = self._ws, None
        if self._reader:
            self._reader.cancel()
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
            self._flush_pending()

    async def close(self) -> None:
        self._closed = True
        if self._reconnect is not None:
            self._reconnect.cancel()
        await self._reset()


class MockStt(SttClient):
    """Offline/test double: the transcript of each utterance is taken from ``script``
    (cycled). Partials appear as audio arrives, like the real service."""

    provider = "mock"

    def __init__(self, script: list[str] | None = None, final_delay_s: float = 0.05) -> None:
        super().__init__()
        self.script = script or ["Explain recursion to me."]
        self.final_delay_s = final_delay_s
        self.audio_bytes: dict[int, int] = {}
        self.count = 0
        self.closed = False
        self.context = ""

    async def start(self) -> None:
        return None

    async def set_context(self, said: str) -> None:
        self.context = said

    def _text_for(self, utt: int) -> str:
        return self.script[(utt - 1) % len(self.script)] if utt > 0 else self.script[0]

    async def append(self, utt: int, pcm24: bytes) -> None:
        n = self.audio_bytes.get(utt, 0) + len(pcm24)
        self.audio_bytes[utt] = n
        words = self._text_for(utt).split()
        shown = min(len(words), n // 24000)  # ~ one word per 0.5 s of audio
        if shown:
            self.on_partial(utt, " ".join(words[:shown]))

    async def commit(self, utt: int) -> None:
        async def later() -> None:
            await asyncio.sleep(self.final_delay_s)
            self.count += 1
            self.on_final(utt, self._text_for(utt))

        asyncio.get_running_loop().create_task(later())

    async def cancel(self, utt: int) -> None:
        self.audio_bytes.pop(utt, None)

    async def close(self) -> None:
        self.closed = True


def create_stt(settings: Any) -> SttClient | None:
    if settings.stt_provider == "off":
        return None
    if settings.stt_provider == "mock":
        return MockStt()
    return OpenAIRealtimeStt(settings)
