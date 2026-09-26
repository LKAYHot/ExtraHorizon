"""Sessions: per-tab isolated state.

Each session owns its emotion engine, chat history, timeline, simulation flag, the
current turn and the voice being spoken. Sessions live in memory only; nothing is
persisted. All mutation happens on the event loop thread (frame analysis runs in a
thread pool but returns plain data that is ingested here).
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .context import build_messages, emotion_note, normalize_subject
from .coord.intent import about_analysis, wants_analysis, wants_refresh, wants_rerun
from .coord.report import fact_sheet
from .emotion.calibration import SENSITIVITY, Calibrator
from .emotion.engine import LABELS, OK, UNKNOWN, EmotionConfig, EmotionEngine, EmotionObservation
from .timeline import Timeline
from .vision.quality import assess_quality
from .vision.types import EMOTIONS, FrameResult

MAX_MESSAGES = 80

# rough valence/arousal of each simulated expression (labelled Demo simulation only)
SIM_VA = {
    "anger": (-0.6, 0.6), "contempt": (-0.4, 0.1), "disgust": (-0.6, 0.3), "fear": (-0.6, 0.5),
    "happiness": (0.7, 0.35), "neutral": (0.0, -0.1), "sadness": (-0.6, -0.3), "surprise": (0.2, 0.6),
}


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ChatCancelled(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Notifier(Protocol):
    def send(self, msg: dict[str, Any]) -> None: ...


@dataclass
class ChatPlan:
    request_id: str
    source: str  # text | voice
    user_msg: dict[str, Any]
    assistant_id: str
    llm_messages: list[dict[str, str]]
    emotion_context: dict[str, Any]
    epoch: int
    generation: int
    turn_no: int
    cancel: asyncio.Event
    gate: asyncio.Event  # set = outputs may reach the learner (speculative turns wait)
    started_ms: int
    cancel_reason: list[str] = field(default_factory=list)
    text_so_far: list[str] = field(default_factory=list)
    committed: bool = False
    # utility-coordination analysis: {"mode": "run" | "context", "refresh", "report_id", "check", "live"}
    analysis: dict[str, Any] | None = None
    voice_done: bool = False  # an analysis report: her spoken summary is over, the rest is written silently
    settled: asyncio.Event = field(default_factory=asyncio.Event)  # the turn has ended (committed or not)
    analysis_sheet: str | None = None  # the exact fact sheet in the prompt (for the grounding check)
    build: dict[str, Any] = field(default_factory=dict)  # to rebuild the prompt once the analysis is ready

    def meta(self, model: str, voice: bool) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "source": self.source,
            "model": model,
            "user_message": self.user_msg,
            "assistant_message_id": self.assistant_id,
            "emotion_context": self.emotion_context,
            "turn_no": self.turn_no,
            "voice": voice,
            "analysis": {k: v for k, v in (self.analysis or {}).items() if k in ("mode", "report_id")} or None,
        }


class Session:
    def __init__(self, sid: str, settings: Any, clock: Callable[[], float] = time.monotonic) -> None:
        self.id = sid
        self.settings = settings
        self.clock = clock
        self.emotion = EmotionEngine(EmotionConfig.from_settings(settings))
        self.calib = Calibrator(settings.emotion_calibration_s, settings.emotion_calibration_min_frames,
                                settings.emotion_adapt_tau_s, settings.emotion_sensitivity)
        self._last_face_t: float | None = None
        self.timeline = Timeline(settings.timeline_window_s)
        self.messages: list[dict[str, Any]] = []
        self.subject = "General"
        self.sim_enabled = False
        self.camera = "unknown"
        self.epoch = 0
        self.vision_conn: Notifier | None = None
        self.live_conn: Any | None = None
        self.speaker: Any | None = None  # voice currently being spoken (turns.Speaker)
        self._chat_generation = 0
        self._chat_plan: ChatPlan | None = None
        self._turn_no = 0
        self._last_note: str | None = None
        self._told_dominant: str | None = None  # what she saw when the learner last spoke
        self.analysis: dict[str, Any] | None = None  # the utility-coordination report on screen (coord/)
        self.coord_params: dict[str, Any] = {}  # the learner's thresholds for it (distance_m, window_days, area_m)
        self.last_active = clock()

    # ------------------------------------------------------------------ plumbing
    def touch(self) -> None:
        self.last_active = self.clock()

    @property
    def busy(self) -> bool:
        return self.vision_conn is not None or self.live_conn is not None or self._chat_plan is not None

    @property
    def current_plan(self) -> ChatPlan | None:
        return self._chat_plan

    def attach_vision(self, conn: Notifier) -> Notifier | None:
        prev, self.vision_conn = self.vision_conn, conn
        return prev

    def detach_vision(self, conn: Notifier) -> None:
        if self.vision_conn is conn:
            self.vision_conn = None

    def attach_live(self, conn: Any) -> Any | None:
        prev, self.live_conn = self.live_conn, conn
        return prev

    def detach_live(self, conn: Any) -> None:
        if self.live_conn is conn:
            self.live_conn = None
            self.stop_speaking()

    def notify(self, *msgs: dict[str, Any]) -> None:
        for conn in (self.vision_conn, self.live_conn):
            if conn is not None:
                for m in msgs:
                    conn.send(m)

    def next_turn_no(self) -> int:
        self._turn_no += 1
        return self._turn_no

    # ------------------------------------------------------------------ voice being spoken
    def set_speaker(self, speaker: Any | None) -> None:
        if self.speaker is not None and self.speaker is not speaker:
            self.speaker.abort_nowait()
        self.speaker = speaker

    def clear_speaker(self, speaker: Any) -> None:
        if self.speaker is speaker:
            self.speaker = None

    def stop_speaking(self) -> bool:
        """Stop the voice right now (barge-in, new question, reset). True if it was talking."""
        sp, self.speaker = self.speaker, None
        if sp is not None:
            sp.abort_nowait()
            return True
        return False

    @property
    def speaker_audible(self) -> bool:
        """Answer audio of the current speaker has reached the learner's browser."""
        return self.speaker is not None and bool(getattr(self.speaker, "began", False))

    @property
    def assistant_active(self) -> bool:
        """Generating or speaking — the learner's voice now counts as an interruption."""
        live = self.live_conn
        playing = bool(getattr(live, "client_playing", False)) if live is not None else False
        plan = self._chat_plan
        return (plan is not None and not plan.voice_done) or self.speaker is not None or playing

    @property
    def chat_plan(self) -> ChatPlan | None:
        return self._chat_plan

    @property
    def writing_silently(self) -> bool:
        """Her spoken summary of an analysis is over and the written report is still coming: the learner's
        voice is not an interruption now (a question is answered once it is clear it is one)."""
        plan = self._chat_plan
        return plan is not None and plan.voice_done and not plan.cancel.is_set() and self.speaker is None

    def recent_assistant_text(self) -> str:
        if self._chat_plan is not None and self._chat_plan.text_so_far:
            return "".join(self._chat_plan.text_so_far)
        for m in reversed(self.messages):
            if m["role"] == "assistant":
                return m["text"]
        return ""

    # ------------------------------------------------------------------ vision → emotions
    def ingest_frame(self, seq: int, frame: FrameResult, t: float, t_ms: int) -> list[dict[str, Any]]:
        if self.camera not in ("active", "unknown"):
            # a frame in flight when the camera was switched off / the tab hidden: ack only
            return [{"type": "tick", "seq": seq, "t": t_ms, "vision": None, "emotion": None}]
        status, reason = assess_quality(frame, self.settings)
        em = frame.emotion
        vision: dict[str, Any] = {
            "faces": frame.faces,
            "boxes": frame.boxes,
            "pose": None if frame.pose is None else {
                "yaw": round(frame.pose[0], 1), "pitch": round(frame.pose[1], 1), "roll": round(frame.pose[2], 1)},
            "brightness": None if frame.brightness is None else round(frame.brightness, 1),
            "raw": None if em is None else {
                "probs": {k: round(v, 3) for k, v in zip(EMOTIONS, em.probs)},
                "valence": None if em.valence is None else round(em.valence, 3),
                "arousal": None if em.arousal is None else round(em.arousal, 3),
            },
            "proc_ms": round(frame.proc_ms, 1),
            "emotion_ms": None if em is None else round(em.ms, 1),
            "quality": status,
            "reason": reason,
            "used_by_engine": not self.sim_enabled,
        }
        tick: dict[str, Any] = {"type": "tick", "seq": seq, "t": t_ms, "vision": vision, "emotion": None}
        out = [tick]
        if not self.sim_enabled:
            if status == OK and em is not None:
                s = self.settings
                if self._last_face_t is not None and t - self._last_face_t > s.emotion_recalibrate_after_s:
                    self.calib.restart()  # a long absence: maybe someone else now — learn the face again
                self._last_face_t = t
                speaking = bool(getattr(self.live_conn, "learner_speaking", False))
                corr = self.calib.observe(t, em, frame.blendshapes, frame.pose, speaking)
                if corr is None:  # learning this person's relaxed face first
                    obs = EmotionObservation(t, None, status="calibrating", reason="calibrating", source="camera")
                else:
                    obs = EmotionObservation(t, corr.probs, corr.valence, corr.arousal, OK, None, "camera",
                                             weight=corr.weight, actions=corr.actions)
                    vision["weight"] = round(corr.weight, 2)
                    vision["actions"] = list(corr.actions)
            else:
                obs = EmotionObservation(t, None, None, None, UNKNOWN, reason, "camera")
            vision["calibration"] = self.calib.public()
            tick["emotion"], extra = self._emotion_step(obs, t_ms)
            out.extend(extra)
        return out

    def recalibrate(self, t: float, t_ms: int) -> list[dict[str, Any]]:
        """Learn the learner's relaxed face again (button, or a different person)."""
        self.calib.restart()
        pub, extra = self._emotion_step(EmotionObservation(t, None, status="calibrating", reason="calibrating"), t_ms)
        return [{"type": "tick", "seq": None, "t": t_ms, "vision": None, "emotion": pub,
                 "calibration": self.calib.public()}, *extra]

    def set_sensitivity(self, level: str) -> dict[str, Any]:
        """calm | balanced | expressive — how readily an expression is reported."""
        if level in SENSITIVITY:
            self.calib.set_sensitivity(level)
            self.emotion.cfg = EmotionConfig.from_settings(self.settings, level)
        return self.calib.public()

    def ingest_sim(self, emotion: str, intensity: float, t: float, t_ms: int) -> list[dict[str, Any]]:
        """Labelled Demo simulation: a chosen expression drives the SAME engine; every sample
        it produces is tagged ``source: simulation``."""
        self.sim_enabled = True
        emotion = emotion if emotion in EMOTIONS else "neutral"
        k = min(1.0, max(0.0, float(intensity)))
        rest = 1.0 - k
        probs = [0.0] * len(EMOTIONS)
        probs[EMOTIONS.index(emotion)] = k
        probs[EMOTIONS.index("neutral")] += rest * 0.7
        others = [i for i, e in enumerate(EMOTIONS) if e not in (emotion, "neutral")]
        for i in others:
            probs[i] += rest * 0.3 / len(others)
        v, a = SIM_VA.get(emotion, (0.0, 0.0))
        obs = EmotionObservation(t, tuple(probs), v * k, a * k, OK, None, "simulation")
        pub, extra = self._emotion_step(obs, t_ms)
        return [{"type": "tick", "seq": None, "t": t_ms, "vision": None, "emotion": pub}, *extra]

    def set_sim(self, enabled: bool, t: float, t_ms: int) -> list[dict[str, Any]]:
        if enabled == self.sim_enabled:
            return []
        self.sim_enabled = enabled
        src = "simulation" if enabled else "camera"
        pub, extra = self._emotion_step(EmotionObservation(t, None, status=UNKNOWN, reason="source_switched", source=src), t_ms)
        return [{"type": "tick", "seq": None, "t": t_ms, "vision": None, "emotion": pub}, *extra]

    def camera_status(self, status: str, t: float, t_ms: int) -> list[dict[str, Any]]:
        self.camera = status
        if status == "active" or self.sim_enabled:
            return []
        pub, extra = self._emotion_step(EmotionObservation(t, None, status=UNKNOWN, reason=f"camera_{status}"), t_ms)
        return [{"type": "tick", "seq": None, "t": t_ms, "vision": None, "emotion": pub}, *extra]

    def vision_disconnected(self, t: float, t_ms: int) -> None:
        self.camera = "disconnected"
        self.sim_enabled = False
        self._emotion_step(EmotionObservation(t, None, status=UNKNOWN, reason="vision_disconnected"), t_ms)

    def _emotion_step(self, obs: EmotionObservation, t_ms: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        state, changes = self.emotion.update(obs)
        pub = state.to_public()
        self.timeline.add_sample(t_ms, pub)
        out: list[dict[str, Any]] = []
        for ch in changes:
            label = LABELS.get(ch.current, ch.current)
            marker = self.timeline.add_marker(t_ms, "emotion", label, ch.current)
            out.append({"type": "marker", "marker": marker})
        # the live preview of what the tutor would be told (sent only when the words change)
        ctx = self._describe(obs.t)
        if ctx["note"] != self._last_note:
            self._last_note = ctx["note"]
            out.append({"type": "emotion_note", "context": ctx})
        return pub, out

    def _describe(self, t: float) -> dict[str, Any]:
        ctx = self.emotion.describe(t)
        ctx["note"] = emotion_note(ctx)  # the exact text added to the prompt (or None)
        return ctx

    def emotion_context(self) -> dict[str, Any]:
        return self._describe(self.clock())

    # ------------------------------------------------------------------ chat turns
    def analysis_messages(self, plan: ChatPlan, report: dict[str, Any] | None) -> list[dict[str, str]]:
        """The prompt of an analysis turn once the analysis is ready (or failed)."""
        b = plan.build
        sheet = fact_sheet(report, mention=b["text"]) if report else None
        plan.analysis_sheet = sheet
        return build_messages(
            self.messages, b["text"], subject=self.subject, emotion_context=b["ctx"],
            history_turns=self.settings.llm_history_turns, name=self.settings.persona_name,
            voice=b["voice"], analysis_sheet=sheet, analysis_mode=(plan.analysis or {}).get("mode"),
        )

    def plan_chat(self, *, message: str | None, subject: str | None, source: str = "text",
                  turn_no: int | None = None, speculative: bool = False, analysis: bool = False) -> ChatPlan:
        if subject:
            self.subject = normalize_subject(subject)
        text = (message or "").strip()
        if not text:
            raise ApiError(422, "empty_message", "Type or say something first.")
        # a newer request (typed or spoken) supersedes an in-flight one and stops the voice
        if self._chat_plan is not None and not self._chat_plan.cancel.is_set():
            self._chat_plan.cancel_reason.append("superseded")
            self._chat_plan.cancel.set()
        self.stop_speaking()
        self._chat_generation += 1
        started = now_ms()
        ctx = self.emotion_context()
        if ctx.get("available") and ctx.get("dominant") == self._told_dominant:
            ctx["unchanged"] = True  # she saw the same last time: don't make her comment again
            ctx["note"] = emotion_note(ctx)
        user_msg = {"id": new_id("m"), "role": "user", "text": text, "source": source, "created": started}
        # the utility-coordination analysis: "run" it first, or answer from the one on screen ("context");
        # anything else is ordinary tutoring even while an analysis is open
        mode = None
        asked = analysis or wants_analysis(text)
        if self.analysis is None:
            mode = "run" if asked else None
        elif analysis or (asked and wants_rerun(text)):
            mode = "run"
        elif asked or about_analysis(text, self.analysis):
            mode = "context"
        sheet = fact_sheet(self.analysis, mention=text) if mode == "context" else None
        gate = asyncio.Event()
        if not speculative:
            gate.set()
        plan = ChatPlan(
            request_id=new_id("r"),
            source=source,
            user_msg=user_msg,
            assistant_id=new_id("m"),
            llm_messages=build_messages(
                self.messages, text, subject=self.subject, emotion_context=ctx,
                history_turns=self.settings.llm_history_turns, name=self.settings.persona_name,
                voice=source == "voice", analysis_sheet=sheet, analysis_mode=mode,
            ),
            emotion_context=ctx,
            epoch=self.epoch,
            generation=self._chat_generation,
            turn_no=turn_no if turn_no is not None else self.next_turn_no(),
            cancel=asyncio.Event(),
            gate=gate,
            started_ms=started,
            analysis=({"mode": mode, "refresh": wants_refresh(text),
                       "report_id": self.analysis["id"] if mode == "context" and self.analysis else None}
                      if mode else None),
            analysis_sheet=sheet,
            build={"text": text, "ctx": ctx, "voice": source == "voice"},
        )
        self._chat_plan = plan
        self.touch()
        return plan

    def confirm_plan(self, plan: ChatPlan, final_text: str) -> None:
        """A speculative turn was right: release its outputs (with the final transcript)."""
        plan.user_msg["text"] = final_text.strip() or plan.user_msg["text"]
        if plan.llm_messages and plan.llm_messages[-1]["role"] == "user":
            plan.llm_messages[-1]["content"] = plan.user_msg["text"]
        if plan.build:
            plan.build["text"] = plan.user_msg["text"]  # an analysis prompt is built from it later
        plan.gate.set()

    def discard_plan(self, plan: ChatPlan, reason: str = "discarded") -> None:
        """Drop a turn without committing anything (``discarded``: the final transcript
        differed from the speculative one; ``merged``: the learner went on talking)."""
        if plan.committed:
            return
        plan.cancel_reason.append(reason)
        plan.cancel.set()

    def interrupt(self, reason: str = "interrupted", *, audible: bool = False) -> bool:
        """Barge-in / stop button: cancel the turn in flight and silence the voice.
        ``audible``: the browser is still playing the (already generated) answer."""
        stopped = self.stop_speaking() or audible
        if self._chat_plan is not None:
            if not self._chat_plan.cancel.is_set():
                self._chat_plan.cancel_reason.append(reason)
                self._chat_plan.cancel.set()
            return True
        if stopped:
            for m in reversed(self.messages):
                if m["role"] == "assistant":
                    m["interrupted"] = True
                    self.notify({"type": "assistant_interrupted", "message_id": m["id"]})
                    break
        return stopped

    def is_current(self, plan: ChatPlan) -> bool:
        return plan.epoch == self.epoch and plan.generation == self._chat_generation

    def commit_chat(self, plan: ChatPlan, text: str, *, model: str, ttft_ms: int | None, elapsed_ms: int,
                    finish_reason: str | None = None, interrupted: bool = False) -> dict[str, Any]:
        if not self.is_current(plan):
            raise ChatCancelled("reset" if plan.epoch != self.epoch else "superseded")
        t_ms = now_ms()
        assistant: dict[str, Any] = {
            "id": plan.assistant_id,
            "role": "assistant",
            "text": text,
            "source": plan.source,
            "created": t_ms,
            "model": model,
            "ttft_ms": ttft_ms,
            "emotion_context": plan.emotion_context,
            "interrupted": interrupted,
        }
        if plan.analysis:
            assistant["analysis"] = {k: v for k, v in plan.analysis.items() if k in ("mode", "report_id", "check", "live")}
        self.messages.extend([plan.user_msg, assistant])
        del self.messages[:-MAX_MESSAGES]
        self._chat_plan = None
        plan.committed = True
        ctx = plan.emotion_context or {}
        self._told_dominant = ctx.get("dominant") if ctx.get("available") else None
        marker = self.timeline.add_marker(t_ms, "answer", "Interrupted" if interrupted else "Answer", plan.assistant_id)
        self.notify({"type": "marker", "marker": marker})
        self.touch()
        return {
            "assistant_message_id": plan.assistant_id,
            "finish_reason": finish_reason,
            "ttft_ms": ttft_ms,
            "elapsed_ms": elapsed_ms,
            "model": model,
            "created": t_ms,
            "interrupted": interrupted,
        }

    def abort_chat(self, plan: ChatPlan) -> None:
        if self._chat_plan is plan:
            self._chat_plan = None

    def retract(self, plan: ChatPlan) -> bool:
        """Undo the exchange just committed by ``plan`` — the learner never heard the answer
        because they went on talking (their words continue the same question)."""
        if not plan.committed or len(self.messages) < 2:
            return False
        if self.messages[-1]["id"] != plan.assistant_id or self.messages[-2]["id"] != plan.user_msg["id"]:
            return False
        del self.messages[-2:]
        plan.committed = False
        return True

    # ------------------------------------------------------------------ reset / snapshots
    def reset(self) -> int:
        self.epoch += 1
        if self._chat_plan is not None:
            self._chat_plan.cancel_reason.append("reset")
            self._chat_plan.cancel.set()
            self._chat_plan = None
        self.stop_speaking()
        if self.live_conn is not None and hasattr(self.live_conn, "on_reset"):
            self.live_conn.on_reset()  # utterances of the old session must not start turns
        self._chat_generation += 1
        self.emotion.reset()
        self.timeline.clear()
        self.messages.clear()
        self.sim_enabled = False
        self._last_note = None
        self._told_dominant = None
        self.analysis = None
        self.coord_params = {}
        self.touch()
        self.notify({"type": "reset", "epoch": self.epoch}, self.snapshot_message())
        return self.epoch

    def snapshot_message(self) -> dict[str, Any]:
        last = self.emotion.last_state
        return {
            "type": "snapshot",
            "epoch": self.epoch,
            "timeline": self.timeline.snapshot(now_ms(), self.settings.timeline_snapshot_points),
            "emotion": None if last is None else last.to_public(),
            "context": self.emotion_context(),
            "sim": {"enabled": self.sim_enabled},
            "calibration": self.calib.public(),
        }

    def state_payload(self, boot_id: str) -> dict[str, Any]:
        snap = self.snapshot_message()
        return {
            "session_id": self.id,
            "boot_id": boot_id,
            "epoch": self.epoch,
            "subject": self.subject,
            "messages": [dict(m) for m in self.messages],
            "timeline": snap["timeline"],
            "emotion": snap["emotion"],
        }


class SessionStore:
    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._sessions: OrderedDict[str, Session] = OrderedDict()

    def __len__(self) -> int:
        return len(self._sessions)

    def get(self, sid: str) -> Session | None:
        return self._sessions.get(sid)

    def get_or_create(self, sid: str) -> Session:
        s = self._sessions.get(sid)
        if s is None:
            self._evict()
            s = Session(sid, self.settings)
            self._sessions[sid] = s
        else:
            self._sessions.move_to_end(sid)
        s.touch()
        return s

    def _evict(self) -> None:
        while len(self._sessions) >= self.settings.max_sessions:
            victim = next((k for k, v in self._sessions.items() if not v.busy), None)
            if victim is None:
                return
            del self._sessions[victim]

    def sweep(self) -> int:
        cutoff = time.monotonic() - self.settings.session_idle_ttl_s
        stale = [k for k, v in self._sessions.items() if v.last_active < cutoff and not v.busy]
        for k in stale:
            del self._sessions[k]
        return len(stale)
