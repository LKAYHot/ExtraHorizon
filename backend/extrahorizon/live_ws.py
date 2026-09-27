"""WebSocket ``/api/live``: the voice conversation.

Client → server
  binary        microphone audio, PCM16 little-endian mono 24 kHz (any frame size)
  {"type":"mic","on":true|false}          voice mode on/off (connects/closes speech-to-text)
  {"type":"voice_out","on":true|false}    speak answers (Fish) or text only
  {"type":"playback","playing":bool}      the browser is (not) playing tutor audio
  {"type":"interrupt"}                    stop button
  {"type":"ping","t":…}

Server → client
  {"type":"hello", …}
  {"type":"vad","speaking":true,"utt":n,"continues":m|null,"barge":bool}
  {"type":"vad","speaking":false,"utt":n,"turn_no":t}
  {"type":"stt","utt":n,"text":…,"final":bool}           live / final transcript of one utterance
  {"type":"heard","utt":n,"turn_no":t,"text":…}          the whole question (continued utterances joined)
  {"type":"stt_ignored","utt":n,"turn_no":t,"reason":"empty|echo|stop","text":…}
  {"type":"turn","event":"meta|delta|done|error|interrupted|dropped","turn_no":t,"data":{…}}
  {"type":"filler","turn_no":t,"text":…}
  {"type":"audio_begin","turn_no":t,"kind":"filler|answer","sample_rate":44100}
  binary        4-byte big-endian turn_no + PCM16LE mono audio of that turn
  {"type":"audio_end","turn_no":t}  {"type":"audio_stop","turn_no":t}  {"type":"barge_in","by":"voice|button"}
  {"type":"stt_error"|"tts_error"|"error", …}

A spoken question: VAD start → audio to STT (with pre-roll) → VAD end → commit. At that
instant a cached filler starts playing and — if the live transcript already has words — a
speculative turn starts on it; the final transcript confirms it (outputs released) or
replaces it.

Turn-taking rules
* The learner pauses mid-sentence and goes on (within ``voice_merge_window_s`` and before
  the tutor started answering aloud): the new words *continue* the same question — the
  pending turn and its filler are dropped and the transcripts are joined.
* The learner talks while the tutor speaks or thinks: barge-in — her voice stops at once,
  the partial answer is kept (marked interrupted). A bare "stop" / "wait" / "стоп" after a
  barge-in only stops her; it does not start a new answer.
* A transcript that repeats what she was just saying is her own voice (echo): ignored.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import struct
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from .sessions import ApiError, Session
from .turns import TurnRunner
from .voice.tags import speakable, strip_tags

log = logging.getLogger("extrahorizon.live")

_WORD = re.compile(r"[\w']+", re.UNICODE)

# "stop talking" commands (English + Russian); a command must contain a core word and
# nothing but these words
STOP_CORE = {
    "stop", "wait", "pause", "enough", "quiet", "hold", "hang", "shut", "cancel", "shush", "shh",
    "стоп", "подожди", "погоди", "хватит", "стой", "тихо", "замолчи", "постой", "остановись", "пауза",
}
STOP_EXTRA = {
    "ok", "okay", "please", "on", "a", "sec", "second", "moment", "minute", "just", "up", "hey",
    "rika", "uh", "um", "hmm", "no", "right", "there", "it", "that's", "thats", "all", "now", "go",
    "ладно", "пожалуйста", "секунду", "минутку", "секундочку", "так", "ну", "эй", "рика", "нет",
    "всё", "все", "давай", "уже", "же",
}


def _norm(text: str) -> str:
    return " ".join(_WORD.findall(strip_tags(text).lower()))


def echo_ratio(user_text: str, assistant_text: str) -> float:
    """How much of the learner's utterance is a *contiguous* repeat of what the tutor just
    said: the share of its word trigrams that occur in her text. Echo repeats her phrases;
    a real follow-up ("What is a base case?") reuses a few of her words but not her phrasing."""
    u = _WORD.findall(user_text.lower())
    a = _WORD.findall(strip_tags(assistant_text[-3000:]).lower())
    if len(u) < 3 or len(a) < 3:
        return 0.0
    theirs = set(zip(a, a[1:], a[2:]))
    ours = list(zip(u, u[1:], u[2:]))
    return sum(1 for t in ours if t in theirs) / len(ours)


def is_stop_command(text: str) -> bool:
    words = _WORD.findall(text.lower())
    if not words or len(words) > 6:
        return False
    return any(w in STOP_CORE for w in words) and all(w in STOP_CORE or w in STOP_EXTRA for w in words)


BACKCHANNEL = {
    "ok", "okay", "k", "yeah", "yes", "yep", "yup", "mm", "mhm", "mmhmm", "hmm", "uh", "huh", "right", "cool", "nice",
    "great", "got", "it", "sure", "thanks", "thank", "you", "i", "see", "alright", "fine", "good", "wow", "oh", "ah",
    "ага", "угу", "да", "ок", "окей", "понятно", "ясно", "хорошо", "спасибо", "класс", "отлично", "ну", "ладно", "понял",
    "поняла", "ого", "ааа", "ммм",
}


def is_backchannel(text: str) -> bool:
    """'Okay', 'got it', 'угу' — listening noises, not a question."""
    words = _WORD.findall(text.lower())
    return 0 < len(words) <= 3 and all(w in BACKCHANNEL for w in words)


_CAP_WORD = re.compile(r"([A-ZА-ЯЁ])([a-zа-яё])")


def join_speech(parts: list[str]) -> str:
    """Join the transcripts of a sentence the learner paused in: "Explain recursion to me"
    + "And please…" → "Explain recursion to me and please…"."""
    out = ""
    for p in (x.strip() for x in parts):
        if not p:
            continue
        if out and not out.endswith((".", "!", "?", "…")) and _CAP_WORD.match(p) and not p.startswith("I "):
            p = p[0].lower() + p[1:]
        out = f"{out} {p}" if out else p
    return out


@dataclass(eq=False)
class Utterance:
    n: int
    started: float
    barge: bool = False  # it interrupted the tutor
    echo_ref: str = ""  # what the tutor was saying when it began (echo check)
    ended: float | None = None
    duration_ms: int = 0
    partial: str = ""
    final: str | None = None  # None until its transcript arrives
    final_evt: asyncio.Event = field(default_factory=asyncio.Event)
    turn_no: int | None = None
    plan: Any = None  # the turn answering it (speculative or confirmed)
    prefix: Utterance | None = None  # the earlier utterance it continues
    merged: bool = False  # continued by a later utterance (which answers for both)
    ignored: str | None = None  # empty | echo | stop | stopped
    cancelled: bool = False  # stop button / barge-in / reset before it was answered
    during_report: bool = False  # began while her analysis report was being written silently

    def chain(self) -> list[Utterance]:
        out: list[Utterance] = []
        u: Utterance | None = self
        while u is not None:
            out.append(u)
            u = u.prefix
        return out[::-1]  # oldest first

    def text(self, final_only: bool = False) -> str:
        parts = []
        for u in self.chain():
            if u.ignored == "echo":
                continue
            t = u.final if u.final is not None else ("" if final_only else u.partial)
            if t and t.strip():
                parts.append(t.strip())
        return join_speech(parts)


class LiveConnection:
    def __init__(self, ws: WebSocket, session: Session, services: Any, settings: Any, boot_id: str) -> None:
        self.ws = ws
        self.session = session
        self.svc = services
        self.s = settings
        self.boot_id = boot_id
        self.out: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue(maxsize=4000)
        self.voice_out = True
        self.client_playing = False
        self.last_played_at = 0.0
        self.mic_on = False
        self.segmenter = None
        self.stt = None
        self._utt_n = 0
        self._utts: dict[int, Utterance] = {}
        self._current: Utterance | None = None
        self._last: Utterance | None = None  # the most recent finished utterance
        self._stopped_turns: set[int] = set()
        self._audible: set[int] = set()  # turns whose audio was sent and not stopped
        self._answered: set[int] = set()  # turns whose answer started (audio, or text when muted)
        self._tasks: set[asyncio.Task] = set()
        self._plan_ids: set[str] = set()  # turns this connection started
        self._closed = False
        self.last_spoke_at = 0.0

    @property
    def learner_speaking(self) -> bool:
        """An utterance is open (the mouth moves for speech, not for an expression)."""
        return self._current is not None

    # ------------------------------------------------------------------ outbound (single writer)
    def send(self, msg: dict[str, Any]) -> None:
        if not self._closed:
            with contextlib.suppress(asyncio.QueueFull):
                self.out.put_nowait(("text", json.dumps(msg, separators=(",", ":"))))

    def audio_begin(self, turn_no: int, kind: str) -> None:
        self._audible.add(turn_no)
        if kind == "answer":
            self._answered.add(turn_no)
        self.send({"type": "audio_begin", "turn_no": turn_no, "kind": kind, "sample_rate": self.s.tts_sample_rate})

    def send_audio(self, turn_no: int, pcm: bytes) -> None:
        if self._closed or turn_no in self._stopped_turns or not pcm:
            return
        self.last_spoke_at = time.monotonic()
        with contextlib.suppress(asyncio.QueueFull):
            self.out.put_nowait(("bytes", struct.pack(">I", turn_no) + pcm))

    def audio_end(self, turn_no: int, failed: str = "") -> None:
        self.send({"type": "audio_end", "turn_no": turn_no, "failed": failed or None})

    def audio_stop(self, turn_no: int) -> None:
        self._stopped_turns.add(turn_no)
        self._audible.discard(turn_no)
        if len(self._stopped_turns) > 256:  # old turns can never come back
            self._stopped_turns = {t for t in self._stopped_turns if t > turn_no - 64}
            self._answered = {t for t in self._answered if t > turn_no - 64}
        self.send({"type": "audio_stop", "turn_no": turn_no})

    def _stop_all_audio(self) -> None:
        for turn_no in sorted(self._audible):
            self.audio_stop(turn_no)

    async def _sender(self) -> None:
        try:
            while True:
                item = await self.out.get()
                if item is None:
                    await self.ws.close(code=4001)
                    return
                kind, payload = item
                if kind == "bytes":
                    await self.ws.send_bytes(payload)
                else:
                    await self.ws.send_text(payload)
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            return

    def supersede(self) -> None:
        self.send({"type": "superseded"})
        with contextlib.suppress(asyncio.QueueFull):
            self.out.put_nowait(None)

    # ------------------------------------------------------------------ lifecycle
    async def run(self) -> None:
        prev = self.session.attach_live(self)
        if prev is not None and prev is not self:
            prev.supersede()
        self.send({
            "type": "hello",
            "boot_id": self.boot_id,
            "config": self.s.public_voice_config(),
            "tts": self.svc.tts.status(),
            "stt": {"provider": self.s.stt_provider, "model": self.s.stt_model, "configured": self.s.stt_configured},
            "vad": bool(getattr(self.svc, "vad_ok", False)),
            "fillers": getattr(self.svc.fillers, "state", "off"),
            "persona": self.s.persona_name,
        })
        sender = asyncio.create_task(self._sender())
        try:
            await self._receiver()
        finally:
            self._closed = True
            superseded = self.session.live_conn is not self
            self.session.detach_live(self)
            plan = self.session.current_plan
            if not superseded and plan is not None and plan.request_id in self._plan_ids:
                # the learner's socket is gone mid-turn (a newer socket's turns are not ours to cancel)
                self.session.interrupt("interrupted")
            for t in list(self._tasks):
                t.cancel()
            sender.cancel()
            with contextlib.suppress(BaseException):
                await sender
            await self._close_stt()

    async def _receiver(self) -> None:
        while True:
            try:
                msg = await self.ws.receive()
            except (WebSocketDisconnect, RuntimeError):
                return
            if msg.get("type") == "websocket.disconnect":
                return
            data = msg.get("bytes")
            if data is not None:
                await self._on_audio(data)
                continue
            text = msg.get("text")
            if text is not None:
                await self._on_message(text)

    async def _on_message(self, text: str) -> None:
        try:
            m = json.loads(text)
            kind = m.get("type")
        except (ValueError, AttributeError):
            self.send({"type": "error", "code": "bad_message", "message": "Invalid JSON."})
            return
        if kind == "mic":
            await self._set_mic(bool(m.get("on")))
        elif kind == "voice_out":
            self.voice_out = bool(m.get("on"))
            if not self.voice_out:
                self.session.stop_speaking()
                self._stop_all_audio()
        elif kind == "playback":
            playing = bool(m.get("playing"))
            if self.client_playing and not playing:
                self.last_played_at = time.monotonic()
            self.client_playing = playing
        elif kind == "interrupt":
            self.interrupt("button")
        elif kind == "ping":
            self.send({"type": "pong", "t": m.get("t")})
        else:
            self.send({"type": "error", "code": "bad_message", "message": f"Unknown message type {kind!r}."})

    def interrupt(self, by: str) -> bool:
        """Barge-in / stop button: silence her now and cancel the turn in flight. Questions
        still waiting for their transcript are cancelled too (Stop means stop)."""
        had_audio = bool(self._audible) or self.client_playing
        # only her *answer* still playing makes a finished answer "interrupted" (not a filler)
        answer_audible = self.client_playing and bool(self._audible & self._answered)
        stopped = self.session.interrupt("interrupted", audible=answer_audible)
        self._stop_all_audio()
        self._cancel_pending()
        if stopped or had_audio:
            self.send({"type": "barge_in", "by": by})
            return True
        return False

    def _cancel_pending(self) -> None:
        for u in self._utts.values():
            if u.ended is not None and not u.merged and (u.final is None or u.plan is not None):
                u.cancelled = True
        if self._last is not None:
            self._last.cancelled = True  # a new utterance must not continue a stopped question

    def on_reset(self) -> None:
        """New session: forget utterances of the old one (a late transcript must not start a turn)."""
        self._cancel_pending()
        for u in self._utts.values():
            u.cancelled = True
        self._utts.clear()
        self._current = None
        self._last = None

    # ------------------------------------------------------------------ microphone
    async def _set_mic(self, on: bool) -> None:
        if on == self.mic_on:
            return
        self.mic_on = on
        if not on:
            self._current = None
            self._last = None
            for u in list(self._utts.values()):  # pending utterances will get no transcript now
                if u.plan is not None and not u.plan.gate.is_set():
                    self.session.discard_plan(u.plan)
            self._utts.clear()
            if self.segmenter is not None:
                self.segmenter.reset()
            await self._close_stt()
            return
        loop = asyncio.get_running_loop()
        try:
            if self.segmenter is None:
                self.segmenter = await loop.run_in_executor(None, self.svc.make_segmenter)
            self.segmenter.reset()
        except Exception as e:  # noqa: BLE001
            log.exception("VAD unavailable")
            self.mic_on = False
            self.send({"type": "error", "code": "vad_unavailable", "message": f"Voice detection unavailable ({type(e).__name__})."})
            return
        self.stt = self.svc.make_stt()
        if self.stt is None:
            self.mic_on = False
            self.send({"type": "error", "code": "stt_unavailable", "message": "Speech-to-text is switched off (EH_STT_PROVIDER=off)."})
            return
        self.stt.on_partial = self._on_partial
        self.stt.on_final = self._on_final
        self.stt.on_error = lambda message: self.send({"type": "stt_error", "message": message})
        try:
            await self.stt.start()  # warm connection: the first utterance does not pay for it
        except Exception as e:  # noqa: BLE001
            self.send({"type": "stt_error", "message": str(e)[:200]})

    async def _close_stt(self) -> None:
        stt, self.stt = self.stt, None
        if stt is not None:
            with contextlib.suppress(Exception):
                await stt.close()

    async def _on_audio(self, pcm: bytes) -> None:
        if not self.mic_on or self.segmenter is None or self.stt is None:
            return
        strict = self.client_playing or self.session.speaker_audible  # her voice is audible
        for ev in self.segmenter.process(pcm, strict):
            if ev.kind == "start":
                await self._utt_start(ev.audio)
            elif ev.kind == "audio" and self._current is not None:
                await self._stt_call(self.stt.append, self._current.n, ev.audio)
            elif ev.kind == "end" and self._current is not None:
                await self._utt_end(ev.duration_ms)

    async def _stt_call(self, fn, *args) -> None:
        try:
            await fn(*args)
        except Exception as e:  # noqa: BLE001
            self.send({"type": "stt_error", "message": f"transcription unavailable ({type(e).__name__})"})

    def _continues(self, prev: Utterance, now: float) -> bool:
        """The learner resumed after a pause: is it the same question?"""
        if prev.ignored == "echo" or prev.ended is None or prev.cancelled:
            return False
        if now - prev.ended > self.s.voice_merge_window_s:
            return False
        if prev.turn_no is not None and prev.turn_no in self._answered:
            return False  # she already started answering aloud → this is an interruption
        plan = prev.plan
        if plan is not None and plan.cancel.is_set():
            return False  # superseded (a typed question) or stopped
        # an answer written but not heard yet (a fast LLM) can still be taken back
        return not (plan is not None and plan.committed and not self.voice_out)

    def _drop(self, u: Utterance, reason: str) -> None:
        """Drop the turn of an utterance (continued / ignored): no answer, no filler."""
        plan = u.plan
        if plan is not None:
            if plan.committed:
                if self.session.retract(plan):  # written, never heard: take it back
                    sp = self.session.speaker
                    if sp is not None and getattr(sp, "plan", None) is plan:
                        self.session.stop_speaking()
                    self.send({"type": "turn", "event": "dropped", "turn_no": plan.turn_no, "data": {"reason": reason}})
            else:
                self.session.discard_plan(plan, reason)
            u.plan = None
        if u.turn_no is not None and u.turn_no in self._audible:
            self.audio_stop(u.turn_no)

    async def _utt_start(self, preroll: bytes) -> None:
        now = time.monotonic()
        self._utt_n += 1
        u = Utterance(self._utt_n, now)
        audible = self.client_playing or self.session.speaker_audible or now - self.last_played_at < 2.0
        if audible:
            u.echo_ref = self.session.recent_assistant_text()
        prev = self._last
        u.during_report = self.session.writing_silently and not self.client_playing
        if prev is not None and self._continues(prev, now):
            u.prefix = prev
            prev.merged = True
            self._drop(prev, "merged")
        elif self.session.assistant_active or self.client_playing:
            u.barge = self.interrupt("voice")
        self._prune(now)
        self._utts[u.n] = u
        self._current = u
        self.send({"type": "vad", "speaking": True, "utt": u.n,
                   "continues": u.prefix.n if u.prefix else None, "barge": u.barge})
        if self.s.stt_context_bias:
            said = strip_tags(speakable(self.session.recent_assistant_text()))
            await self._stt_call(self.stt.set_context, said)  # type: ignore[union-attr]
        await self._stt_call(self.stt.append, u.n, preroll)  # type: ignore[union-attr]

    async def _utt_end(self, duration_ms: int) -> None:
        u = self._current
        self._current = None
        if u is None:
            return
        u.ended = time.monotonic()
        u.duration_ms = duration_ms
        u.turn_no = self.session.next_turn_no()  # before commit: a fast final must find it
        self._last = u
        self.send({"type": "vad", "speaking": False, "utt": u.n, "turn_no": u.turn_no})
        await self._stt_call(self.stt.commit, u.n)  # type: ignore[union-attr]
        self._spawn(self._final_watchdog(u))
        heard = u.text()
        stop_like = is_stop_command(heard) or (u.barge and duration_ms < 1200)
        # a filler the instant the learner stops (covers transcription + first token + first audio)
        spoken_ms = sum(x.duration_ms for x in u.chain())
        if (self.s.fillers_enabled and self.voice_out and not stop_like and not u.during_report
                and spoken_ms >= self.s.filler_min_utterance_ms and getattr(self.svc.fillers, "ready", False)):
            last = self.session.emotion.last_state
            filler = self.svc.fillers.pick(last.dominant if last else None)
            if filler is not None:
                self.session.stop_speaking()
                self.audio_begin(u.turn_no, "filler")
                self.send({"type": "filler", "turn_no": u.turn_no, "text": strip_tags(filler.text)})
                step = self.s.tts_sample_rate // 5 * 2  # 200 ms per frame
                for i in range(0, len(filler.pcm), step):
                    self.send_audio(u.turn_no, filler.pcm[i : i + step])
        # speculative start on the live transcript (released only if the final agrees) — not on
        # a stop command, and not on what already sounds like her own voice (echo)
        looks_echo = bool(u.echo_ref) and echo_ratio(u.partial, u.echo_ref) >= 0.6
        if (self.s.stt_speculative and len(_WORD.findall(heard)) >= 2 and not is_stop_command(heard)
                and not looks_echo and not u.during_report):
            try:
                plan = self.session.plan_chat(message=heard, subject=None, source="voice",
                                              turn_no=u.turn_no, speculative=True)
            except ApiError:
                return
            u.plan = plan
            self._spawn(self._run_turn(plan))

    async def _final_watchdog(self, u: Utterance) -> None:
        """The transcript normally arrives ≈0.5 s after commit; never leave a turn hanging."""
        await asyncio.sleep(self.s.stt_final_timeout_s)
        if u.final is None and u.n in self._utts:
            log.warning("no transcript for utterance %s after %.1fs — using the live one", u.n, self.s.stt_final_timeout_s)
            await self._handle_final(u.n, u.partial)

    def _on_partial(self, utt: int, text: str) -> None:
        u = self._utts.get(utt)
        if u is not None:
            u.partial = text
        self.send({"type": "stt", "utt": utt, "text": text, "final": False})

    def _on_final(self, utt: int, text: str) -> None:
        self._spawn(self._handle_final(utt, text))

    async def _handle_final(self, utt: int, text: str) -> None:
        u = self._utts.pop(utt, None)
        text = (text or "").strip()
        if u is None:
            return
        self.send({"type": "stt", "utt": utt, "text": text, "final": True})
        u.final = text
        if not _WORD.findall(text):
            u.ignored = "empty"
        elif u.echo_ref and echo_ratio(text, u.echo_ref) >= 0.6:
            u.ignored = "echo"
        u.final_evt.set()
        if u.merged:
            return  # a later utterance continues this one and answers for both
        if u.cancelled:  # Stop / barge-in / new session came first: never answer it now
            self._ignore(u, "stopped", text)
            return
        for p in u.chain()[:-1]:  # the utterances it continues (their transcripts came first)
            if p.final is None:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(p.final_evt.wait(), self.s.stt_final_timeout_s)
        if u.merged or self._closed:
            return
        if u.cancelled:
            self._ignore(u, "stopped", text)
            return
        full = u.text(final_only=True)
        if not _WORD.findall(full):
            self._ignore(u, u.ignored or "empty", text)
            return
        if is_stop_command(full) and any(x.barge for x in u.chain()):
            self._ignore(u, "stop", full)  # "wait, stop" only silences her
            return
        if u.during_report and self.session.writing_silently:
            if is_backchannel(full):
                self._ignore(u, "backchannel", full)  # "okay", "угу": let her finish the written report
                return
            report = self.session.chat_plan
            self.session.interrupt("interrupted")  # a real question: keep the report so far (interrupted) …
            if report is not None:  # … committed before the new question becomes the current turn
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(report.settled.wait(), 2.0)
        self.send({"type": "heard", "utt": u.n, "turn_no": u.turn_no, "text": full})
        plan = u.plan
        if plan is not None and not plan.cancel.is_set() and _norm(full) == _norm(plan.user_msg["text"]):
            self.session.confirm_plan(plan, full)  # speculation was right — release it
            return
        if plan is not None:
            self.session.discard_plan(plan)
        try:
            u.plan = self.session.plan_chat(message=full, subject=None, source="voice", turn_no=u.turn_no)
        except ApiError:
            return
        self._spawn(self._run_turn(u.plan))

    def _ignore(self, u: Utterance, reason: str, text: str) -> None:
        u.ignored = u.ignored or reason
        self._drop(u, "discarded")
        self.send({"type": "stt_ignored", "utt": u.n, "turn_no": u.turn_no, "reason": reason, "text": text})

    async def _run_turn(self, plan: Any) -> None:
        if len(self._plan_ids) > 256:
            self._plan_ids.clear()  # only a turn still in flight matters
        self._plan_ids.add(plan.request_id)
        runner = TurnRunner(self.session, plan, self.svc.llm, self.s, self.svc.tts, self,
                            coord=getattr(self.svc, "coord", None), hub=getattr(self.svc, "hub", None))
        async for name, data in runner.events():
            if name == "discarded":
                return
            if name == "delta" and not (self.voice_out and getattr(self.svc.tts, "configured", False)):
                self._answered.add(plan.turn_no)  # text-only: the answer is visible
            self.send({"type": "turn", "event": name, "turn_no": plan.turn_no, "data": data})

    def _prune(self, now: float) -> None:
        for n, u in list(self._utts.items()):
            if u.ended is not None and now - u.ended > 60:
                del self._utts[n]

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
