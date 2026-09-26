"""One tutor turn: LLM stream → text deltas → TTS chunks → voice audio.

``TurnRunner.events()`` is consumed by the SSE chat route (typed questions) and by the
live voice socket (spoken questions). The LLM is read by a background producer so that:

* a *speculative* turn (started on the live transcript the moment the learner stops
  talking) keeps generating text and voice while its outputs are held behind
  ``plan.gate``; the final transcript either confirms it (outputs released — saves the
  ~0.4 s transcription wait) or discards it silently;
* every chunk the splitter releases goes to Fish immediately (first audio after the first
  clause, not after the whole answer); the audio keeps playing after the text is done;
* barge-in / stop / a newer question / reset cancel the turn: the voice stops at once and
  an interrupted answer is committed with what was generated so far (marked interrupted).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, Protocol

import anyio

from .llm import BaseLLM, LLMError, StreamInfo, map_openai_error
from .sessions import ChatCancelled, ChatPlan, Session
from .voice.fish import TtsEngine, TtsError
from .voice.splitter import TtsSplitter

log = logging.getLogger("extrahorizon.turns")


class AudioSink(Protocol):
    voice_out: bool

    def audio_begin(self, turn_no: int, kind: str) -> None: ...
    def send_audio(self, turn_no: int, pcm: bytes) -> None: ...
    def audio_end(self, turn_no: int, failed: str = "") -> None: ...
    def audio_stop(self, turn_no: int) -> None: ...
    def send(self, msg: dict[str, Any]) -> None: ...


async def _next_or_cancel(agen: AsyncIterator[Any], timeout: float, cancel: asyncio.Event) -> tuple[str, Any]:
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
        await nxt
    return ("cancel", None) if stop in done else ("timeout", None)


class Speaker:
    """Streams one reply to Fish and its audio to the learner's browser."""

    def __init__(self, tts: TtsEngine, sink: AudioSink, plan: ChatPlan, settings: Any, session: Session) -> None:
        self.tts = tts
        self.sink = sink
        self.plan = plan
        self.s = settings
        self.session = session
        self.splitter = TtsSplitter(settings.tts_first_chunk_chars, settings.tts_chunk_chars)
        self.tts_session = None
        self._pump: asyncio.Task | None = None
        self.aborted = False
        self.ok = False
        self.began = False  # answer audio has been sent to the browser
        self.first_audio_ms: int | None = None
        self._t0 = time.monotonic()

    async def start(self) -> bool:
        try:
            self.tts_session = await self.tts.open_session()
            await self.tts_session.begin()  # voice loads while the LLM writes its first words
        except (TtsError, Exception) as e:  # noqa: BLE001 — voice failure never breaks the chat
            msg = e.message if isinstance(e, TtsError) else f"voice error ({type(e).__name__})"
            log.warning("tts unavailable for turn %s: %s", self.plan.turn_no, msg)
            self.sink.send({"type": "tts_error", "turn_no": self.plan.turn_no, "message": msg})
            return False
        if self.plan.cancel.is_set() or not self.session.is_current(self.plan):
            # cancelled while the voice was connecting (a slow dial): registering now would
            # silence the newer turn's voice
            await self.tts_session.abort()
            return False
        self.ok = True
        self.session.set_speaker(self)
        self._pump = asyncio.create_task(self._pump_audio())
        return True

    async def feed(self, delta: str) -> None:
        if self.ok and not self.aborted:
            for chunk in self.splitter.feed(delta):
                await self.tts_session.send(chunk)  # type: ignore[union-attr]

    async def finish(self) -> None:
        if self.ok and not self.aborted:
            for chunk in self.splitter.flush():
                await self.tts_session.send(chunk)  # type: ignore[union-attr]
            await self.tts_session.finish()  # type: ignore[union-attr]

    async def _pump_audio(self) -> None:
        try:
            async for pcm in self.tts_session.audio():  # type: ignore[union-attr]
                if self.aborted:
                    break
                if not self.plan.gate.is_set():
                    await self.plan.gate.wait()  # speculative: hold the voice until confirmed
                if self.aborted:
                    break
                if not self.began:
                    self.began = True
                    self.first_audio_ms = int((time.monotonic() - self._t0) * 1000)
                    self.sink.audio_begin(self.plan.turn_no, "answer")
                self.sink.send_audio(self.plan.turn_no, pcm)
        except asyncio.CancelledError:
            pass
        finally:
            if not self.aborted and self.began:
                failed = getattr(self.tts_session, "failed", "") or ""
                self.sink.audio_end(self.plan.turn_no, failed)
            elif not self.aborted:
                failed = getattr(self.tts_session, "failed", "") or ""
                if failed:
                    self.sink.send({"type": "tts_error", "turn_no": self.plan.turn_no, "message": failed})
            self.session.clear_speaker(self)

    def abort_nowait(self) -> None:
        """Stop talking now (called from sync code: barge-in, supersede, reset)."""
        if self.aborted:
            return
        self.aborted = True
        if self.began:
            # only audio that reached the browser needs stopping; a speculative voice that
            # was never released must not silence the filler / the replacement answer that
            # share its turn number
            self.sink.audio_stop(self.plan.turn_no)
        if self._pump is not None:
            self._pump.cancel()
        if self.tts_session is not None:
            asyncio.get_running_loop().create_task(self.tts_session.abort())


class TurnRunner:
    def __init__(self, session: Session, plan: ChatPlan, llm: BaseLLM, settings: Any,
                 tts: TtsEngine | None = None, sink: AudioSink | None = None) -> None:
        self.session = session
        self.plan = plan
        self.llm = llm
        self.s = settings
        self.tts = tts
        self.sink = sink
        self._q: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
        self.speaker: Speaker | None = None

    @property
    def voice(self) -> bool:
        return bool(self.tts is not None and getattr(self.tts, "configured", False)
                     and self.sink is not None and getattr(self.sink, "voice_out", False))

    async def events(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        plan = self.plan
        producer = asyncio.create_task(self._produce())
        try:
            if not plan.gate.is_set():
                gate = asyncio.ensure_future(plan.gate.wait())
                cancel = asyncio.ensure_future(plan.cancel.wait())
                try:  # (an error before confirmation is shown once confirmed — or vanishes with the plan)
                    await asyncio.wait({gate, cancel}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    gate.cancel()
                    cancel.cancel()
                if not plan.gate.is_set():
                    # the final transcript contradicted the speculative one: vanish quietly
                    with contextlib.suppress(BaseException):
                        await producer
                    yield "discarded", {"turn_no": plan.turn_no}
                    return
            yield "meta", plan.meta(self.llm.model, self.voice)
            while True:
                ev = await self._q.get()
                if ev is None:
                    return
                yield ev
        finally:
            if not producer.done():
                producer.cancel()
                with anyio.CancelScope(shield=True):
                    with contextlib.suppress(BaseException):
                        await producer

    async def _await_release(self, timeout: float) -> None:
        plan = self.plan
        gate = asyncio.ensure_future(plan.gate.wait())
        cancel = asyncio.ensure_future(plan.cancel.wait())
        try:
            await asyncio.wait({gate, cancel}, timeout=max(0.1, timeout), return_when=asyncio.FIRST_COMPLETED)
        finally:
            gate.cancel()
            cancel.cancel()
        if plan.cancel.is_set():
            raise ChatCancelled(plan.cancel_reason[0] if plan.cancel_reason else "discarded")
        if not plan.gate.is_set():  # never confirmed (the transcript was lost): drop the plan
            self.session.discard_plan(plan)
            raise ChatCancelled("discarded")

    async def _produce(self) -> None:
        plan, session, llm, s = self.plan, self.session, self.llm, self.s
        put = self._q.put_nowait
        t0 = time.monotonic()
        committed = False
        parts: list[str] = []
        ttft: float | None = None
        info = StreamInfo(model=llm.model)
        agen = None
        try:
            if not llm.configured:
                raise LLMError("llm_not_configured", "OPENAI_API_KEY is not set on the server. Put it in .env and restart.", False)
            if self.voice:
                self.speaker = Speaker(self.tts, self.sink, plan, s, session)  # type: ignore[arg-type]
                if not await self.speaker.start():
                    self.speaker = None
            agen = llm.stream(plan.llm_messages)
            while True:
                budget = t0 + s.llm_total_timeout_s - time.monotonic()
                step = s.llm_first_token_timeout_s if ttft is None else s.llm_idle_timeout_s
                timeout = min(step, budget)
                if timeout <= 0:
                    raise LLMError("llm_timeout", "The answer took too long. Retry.", True)
                kind, chunk = await _next_or_cancel(agen, timeout, plan.cancel)
                if kind == "end":
                    break
                if kind == "cancel":  # the first reason is the cause (later ones are follow-ups)
                    raise ChatCancelled(plan.cancel_reason[0] if plan.cancel_reason else "superseded")
                if kind == "timeout":
                    raise LLMError("llm_timeout", "The model did not start answering in time. Retry." if ttft is None
                                   else "The answer stalled. Retry.", True)
                if isinstance(chunk, StreamInfo):
                    info = chunk
                    continue
                if chunk:
                    if ttft is None:
                        ttft = time.monotonic() - t0
                    parts.append(chunk)
                    plan.text_so_far.append(chunk)
                    put(("delta", {"text": chunk}))
                    if self.speaker is not None:
                        await self.speaker.feed(chunk)
            text = "".join(parts).strip()
            if not text:
                raise LLMError("llm_empty", "The model returned an empty answer. Retry.", True)
            if self.speaker is not None:
                await self.speaker.finish()
            if not plan.gate.is_set():
                # speculative and already complete: it may be committed only once the final
                # transcript has confirmed it (a mismatch must leave no trace in the history)
                await self._await_release(t0 + s.llm_total_timeout_s + s.stt_final_timeout_s - time.monotonic())
            done = session.commit_chat(
                plan, text, model=info.model, ttft_ms=None if ttft is None else int(ttft * 1000),
                elapsed_ms=int((time.monotonic() - t0) * 1000), finish_reason=info.finish_reason,
            )
            committed = True
            llm.note_ok()
            log.info("turn %s done (%s) ttft=%sms", plan.turn_no, plan.source, done["ttft_ms"])
            put(("done", done))
        except ChatCancelled as c:
            if self.speaker is not None:
                self.speaker.abort_nowait()
            if c.code == "interrupted" and not plan.gate.is_set():
                # stopped before the question was even confirmed: the learner never saw it
                put(("dropped", {"reason": "stopped"}))
            elif c.code == "interrupted" and session.is_current(plan):
                partial = "".join(parts).strip()
                if partial:
                    done = session.commit_chat(plan, partial, model=info.model,
                                               ttft_ms=None if ttft is None else int(ttft * 1000),
                                               elapsed_ms=int((time.monotonic() - t0) * 1000), interrupted=True)
                    committed = True
                    put(("interrupted", done))
                else:
                    put(("error", {"code": "interrupted", "message": "Interrupted.", "retryable": True}))
            elif c.code in ("discarded", "merged"):
                # nothing is committed; if the turn was already visible the client removes it
                put(("dropped", {"reason": c.code}))
            else:
                msg = "The session was reset." if c.code == "reset" else "A newer request replaced this one."
                put(("error", {"code": c.code, "message": msg, "retryable": c.code != "reset"}))
        except asyncio.CancelledError:
            if self.speaker is not None:
                self.speaker.abort_nowait()
            raise
        except Exception as e:  # noqa: BLE001 — every failure ends the turn with a clear error
            if self.speaker is not None:
                self.speaker.abort_nowait()
            err = e if isinstance(e, LLMError) else map_openai_error(e)
            llm.note_error(err)
            log.warning("turn %s failed: %s", plan.turn_no, err.code)
            put(("error", err.public()))
        finally:
            if not committed:
                session.abort_chat(plan)
            if agen is not None:
                with anyio.CancelScope(shield=True):
                    with contextlib.suppress(BaseException):
                        await agen.aclose()  # type: ignore[attr-defined]
            put(None)
