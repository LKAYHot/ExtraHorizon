"""Sessions: per-tab isolated state.

Each session owns its engine (EMA / hold / cooldown), calibration baseline, chat
history, events and timeline. Sessions live in memory only; nothing is persisted.
All mutation happens on the event loop thread (frame analysis runs in a thread
pool but returns plain data that is ingested here).
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, Protocol

from .context import (
    EXPLAIN_DIFFERENTLY_USER_TEXT,
    adaptation_instruction,
    build_messages,
    normalize_subject,
    pick_strategy,
)
from .engine import (
    CALIBRATING,
    OK,
    POSSIBLE_CONFUSION,
    UNKNOWN,
    EngineConfig,
    EngineEvent,
    Observation,
    StateEngine,
    new_id,
)
from .timeline import Timeline
from .vision.types import FrameResult
from .vision.proxy import ConfusionProxy, ProxyParams, assess_quality, extract_features

MAX_MESSAGES = 80
MAX_EVENTS = 100


def now_ms() -> int:
    return int(time.time() * 1000)


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
    mode: str
    user_msg: dict[str, Any]
    assistant_id: str
    llm_messages: list[dict[str, str]]
    adaptation: dict[str, Any] | None
    event_id: str | None
    epoch: int
    generation: int
    cancel: asyncio.Event
    started_ms: int
    cancel_reason: list[str] = field(default_factory=list)

    def meta(self, model: str) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "mode": self.mode,
            "model": model,
            "user_message": self.user_msg,
            "assistant_message_id": self.assistant_id,
            "adaptation": self.adaptation,
        }


class Session:
    def __init__(self, sid: str, settings: Any, clock: Callable[[], float] = time.monotonic) -> None:
        self.id = sid
        self.settings = settings
        self.clock = clock  # the same monotonic clock the engine observations use
        self.engine = StateEngine(EngineConfig.from_settings(settings))
        self.proxy = ConfusionProxy(ProxyParams.from_settings(settings))
        self.timeline = Timeline(settings.timeline_window_s)
        self.messages: list[dict[str, Any]] = []
        self.events: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._event_mono: dict[str, float] = {}
        self._chain_adaptations: dict[str, int] = {}
        self.subject = "General"
        self.sim_enabled = False
        self.camera = "unknown"
        self.epoch = 0
        self.current_answer_id: str | None = None
        self.relief_answer_id: str | None = None
        self.vision_conn: Notifier | None = None
        self._chat_generation = 0
        self._chat_plan: ChatPlan | None = None
        self.last_active = clock()

    # ------------------------------------------------------------------ plumbing
    def touch(self) -> None:
        self.last_active = self.clock()

    @property
    def busy(self) -> bool:
        return self.vision_conn is not None or self._chat_plan is not None

    def attach_vision(self, conn: Notifier) -> Notifier | None:
        prev, self.vision_conn = self.vision_conn, conn
        return prev

    def detach_vision(self, conn: Notifier) -> None:
        if self.vision_conn is conn:
            self.vision_conn = None

    def notify(self, *msgs: dict[str, Any]) -> None:
        conn = self.vision_conn
        if conn is not None:
            for m in msgs:
                conn.send(m)

    # ------------------------------------------------------------------ vision / engine
    def ingest_frame(self, seq: int, frame: FrameResult, t: float, t_ms: int) -> list[dict[str, Any]]:
        if self.camera not in ("active", "unknown"):
            # a frame that was in flight when the camera was switched off / the tab was
            # hidden must not overwrite the "camera off" state — acknowledge, don't ingest
            return [{"type": "tick", "seq": seq, "t": t_ms, "vision": None, "engine": None}]
        status, reason = assess_quality(frame, self.settings)
        vision: dict[str, Any] = {
            "faces": frame.faces,
            "boxes": frame.boxes,
            "pose": None
            if frame.pose is None
            else {"yaw": round(frame.pose[0], 1), "pitch": round(frame.pose[1], 1), "roll": round(frame.pose[2], 1)},
            "brightness": None if frame.brightness is None else round(frame.brightness, 1),
            "features": None,
            "baseline": None,
            "contrib": None,
            "proxy": None,
            "calibration": None,
            "proc_ms": round(frame.proc_ms, 1),
        }
        value: float | None = None
        if status == OK and frame.blendshapes is not None:
            feats = extract_features(frame.blendshapes)
            vision["features"] = {k: round(v, 3) for k, v in feats.items()}
            reading = self.proxy.update(t, feats)
            if reading.status == CALIBRATING:
                status, reason = CALIBRATING, "calibrating"
                vision["calibration"] = {
                    "progress": round(reading.progress, 2),
                    "seconds": self.proxy.params.calibration_s,
                }
            else:
                value = reading.value
                vision["proxy"] = None if value is None else round(value, 3)
                vision["contrib"] = reading.contrib
                if self.proxy.baseline is not None:
                    vision["baseline"] = {k: round(v, 3) for k, v in self.proxy.baseline.items()}
        else:
            self.proxy.note_absence(t)
        vision["quality"] = status
        vision["reason"] = reason
        vision["used_by_engine"] = not self.sim_enabled

        tick: dict[str, Any] = {"type": "tick", "seq": seq, "t": t_ms, "vision": vision, "engine": None}
        out = [tick]
        if not self.sim_enabled:
            engine_pub, extra = self._engine_step(Observation(t, value, status, reason, "camera"), t_ms)
            tick["engine"] = engine_pub
            out.extend(extra)
        return out

    def ingest_sim(self, value: float, t: float, t_ms: int) -> list[dict[str, Any]]:
        """Demo simulation mode: a manually controlled value drives the SAME engine.
        Every sample/event it produces is tagged ``source: simulation``."""
        self.sim_enabled = True
        v = min(1.0, max(0.0, float(value)))
        engine_pub, extra = self._engine_step(Observation(t, v, OK, None, "simulation"), t_ms)
        return [{"type": "tick", "seq": None, "t": t_ms, "vision": None, "engine": engine_pub}, *extra]

    def set_sim(self, enabled: bool, t: float, t_ms: int) -> list[dict[str, Any]]:
        if enabled == self.sim_enabled:
            return []
        self.sim_enabled = enabled
        src = "simulation" if enabled else "camera"
        engine_pub, extra = self._engine_step(Observation(t, None, UNKNOWN, "source_switched", src), t_ms)
        return [{"type": "tick", "seq": None, "t": t_ms, "vision": None, "engine": engine_pub}, *extra]

    def camera_status(self, status: str, t: float, t_ms: int) -> list[dict[str, Any]]:
        self.camera = status
        if status == "active" or self.sim_enabled:
            return []
        engine_pub, extra = self._engine_step(Observation(t, None, UNKNOWN, f"camera_{status}", "camera"), t_ms)
        return [{"type": "tick", "seq": None, "t": t_ms, "vision": None, "engine": engine_pub}, *extra]

    def vision_disconnected(self, t: float, t_ms: int) -> None:
        """The last vision socket closed: nothing is measured any more, so the engine
        must say "unknown" instead of freezing on its last value (camera or simulation)."""
        self.camera = "disconnected"
        self.sim_enabled = False
        self._engine_step(Observation(t, None, UNKNOWN, "vision_disconnected", "camera"), t_ms)

    def recalibrate(self) -> None:
        self.proxy.reset()

    def _engine_step(self, obs: Observation, t_ms: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        state, evs = self.engine.update(obs)
        self.timeline.add_sample(t_ms, state.raw, state.smoothed, state.status, state.source)
        return state.to_public(self.engine.cfg), self._register_events(evs, t_ms)

    def _register_events(self, evs: list[EngineEvent], t_ms: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for e in evs:
            if e.kind == POSSIBLE_CONFUSION:
                answer_id = self.current_answer_id
                status = "offered" if answer_id else "unattached"
                label = "Possible confusion detected"
                marker = self.timeline.add_marker(t_ms, "event", label, e.id)
            else:
                answer_id = self.relief_answer_id
                status = "info"
                label = "Confusion proxy decreased (observed)"
                marker = self.timeline.add_marker(t_ms, "decrease", label, e.id)
            pub = {
                "id": e.id,
                "kind": e.kind,
                "label": label,
                "t": t_ms,
                "source": e.source,
                "smoothed": round(e.smoothed, 3),
                "raw": round(e.raw, 3),
                "held_s": round(e.held_s, 2),
                "rule": self.engine.cfg.rule(),
                "answer_id": answer_id,
                "status": status,
            }
            if e.kind != POSSIBLE_CONFUSION:
                pub["relief"] = {
                    "threshold": self.engine.cfg.relief_threshold,
                    "hold_s": self.engine.cfg.relief_hold_s,
                }
            self.events[e.id] = pub
            self._event_mono[e.id] = e.t
            while len(self.events) > MAX_EVENTS:
                old, _ = self.events.popitem(last=False)
                self._event_mono.pop(old, None)
            out.append({"type": "event", "event": pub})
            out.append({"type": "marker", "marker": marker})
        return out

    # ------------------------------------------------------------------ chat
    def _latest_answer(self) -> dict[str, Any] | None:
        for m in reversed(self.messages):
            if m["role"] == "assistant":
                return m
        return None

    def _expire_offers(self, reason_status: str = "expired") -> list[dict[str, Any]]:
        msgs = []
        for ev in self.events.values():
            if ev["kind"] == POSSIBLE_CONFUSION and ev["status"] in ("offered", "unattached"):
                ev["status"] = reason_status
                msgs.append({"type": "event_update", "event": ev})
        return msgs

    def _offerable_event(self, event_id: str | None) -> dict[str, Any]:
        ev = self.events.get(event_id or "")
        if ev is None or ev["kind"] != POSSIBLE_CONFUSION:
            raise ApiError(409, "no_active_event", "There is no active 'possible confusion' event to adapt to.")
        if ev["status"] != "offered":
            raise ApiError(409, "event_not_active", f"This event is already {ev['status']}.")
        if self.clock() - self._event_mono.get(ev["id"], 0.0) > self.settings.event_ttl_s:
            ev["status"] = "expired"
            self.notify({"type": "event_update", "event": ev})
            raise ApiError(409, "event_expired", "This event is too old — ask again or wait for a new one.")
        latest = self._latest_answer()
        if latest is None or ev["answer_id"] != latest["id"]:
            raise ApiError(409, "event_stale", "This event belongs to a different answer.")
        return ev

    def plan_chat(
        self,
        *,
        mode: str,
        message: str | None,
        event_id: str | None,
        subject: str | None,
    ) -> ChatPlan:
        s = self.settings
        if subject:
            self.subject = normalize_subject(subject)
        strategy = None
        adaptation = None
        if mode == "normal":
            text = (message or "").strip()
            if not text:
                raise ApiError(422, "empty_message", "Type a question first.")
            user_text = text
        elif mode == "explain_differently":
            ev = self._offerable_event(event_id)
            target = self._latest_answer()
            assert target is not None  # guaranteed by _offerable_event
            chain_root = target.get("chain_root") or target["id"]
            strategy = pick_strategy(self._chain_adaptations.get(chain_root, 0))
            user_text = EXPLAIN_DIFFERENTLY_USER_TEXT
            adaptation = {
                "event_id": ev["id"],
                "event_t": ev["t"],
                "strategy": strategy.public(),
                "signal": {
                    "source": ev["source"],
                    "smoothed": ev["smoothed"],
                    "raw": ev["raw"],
                    "held_s": ev["held_s"],
                    "label": "confusion proxy (estimate)",
                },
                "rule": ev["rule"],
                "instruction": adaptation_instruction(strategy),
                "adapted_from": target["id"],
                "chain_root": chain_root,
            }
        else:
            raise ApiError(422, "bad_mode", f"Unknown mode {mode!r}.")

        # a newer request of the same session supersedes an in-flight one
        if self._chat_plan is not None:
            self._chat_plan.cancel_reason.append("superseded")
            self._chat_plan.cancel.set()
        if mode == "normal":
            self.notify(*self._expire_offers())

        self._chat_generation += 1
        started = now_ms()
        user_msg = {"id": new_id("m"), "role": "user", "text": user_text, "mode": mode, "created": started}
        plan = ChatPlan(
            request_id=new_id("r"),
            mode=mode,
            user_msg=user_msg,
            assistant_id=new_id("m"),
            llm_messages=build_messages(
                self.messages,
                user_text,
                subject=self.subject,
                strategy=strategy,
                history_turns=s.llm_history_turns,
            ),
            adaptation=adaptation,
            event_id=adaptation["event_id"] if adaptation else None,
            epoch=self.epoch,
            generation=self._chat_generation,
            cancel=asyncio.Event(),
            started_ms=started,
        )
        self._chat_plan = plan
        # events that fire while this answer streams belong to it
        self.current_answer_id = plan.assistant_id
        self.touch()
        return plan

    def is_current(self, plan: ChatPlan) -> bool:
        return plan.epoch == self.epoch and plan.generation == self._chat_generation

    def commit_chat(
        self,
        plan: ChatPlan,
        text: str,
        *,
        model: str,
        ttft_ms: int | None,
        elapsed_ms: int,
        finish_reason: str | None = None,
    ) -> dict[str, Any]:
        if not self.is_current(plan):
            raise ChatCancelled("reset" if plan.epoch != self.epoch else "superseded")
        t_ms = now_ms()
        assistant: dict[str, Any] = {
            "id": plan.assistant_id,
            "role": "assistant",
            "text": text,
            "mode": plan.mode,
            "created": t_ms,
            "model": model,
            "ttft_ms": ttft_ms,
            "adaptation": plan.adaptation,
            "chain_root": plan.adaptation["chain_root"] if plan.adaptation else plan.assistant_id,
        }
        self.messages.extend([plan.user_msg, assistant])
        del self.messages[:-MAX_MESSAGES]
        self._chat_plan = None
        self.current_answer_id = plan.assistant_id
        self.engine.rearm()  # a new answer is a new episode

        out: list[dict[str, Any]] = []
        # offers that point at an older answer can no longer be used
        for ev in self.events.values():
            if (
                ev["kind"] == POSSIBLE_CONFUSION
                and ev["status"] == "offered"
                and ev["answer_id"] != plan.assistant_id
                and ev["id"] != plan.event_id
            ):
                ev["status"] = "expired"
                out.append({"type": "event_update", "event": ev})
        if plan.adaptation:
            root = plan.adaptation["chain_root"]
            self._chain_adaptations[root] = self._chain_adaptations.get(root, 0) + 1
            ev = self.events.get(plan.event_id or "")
            if ev is not None:
                ev["status"] = "used"
                ev["used_by"] = plan.assistant_id
                out.append({"type": "event_update", "event": ev})
            marker = self.timeline.add_marker(t_ms, "adapted", "Adapted answer", plan.assistant_id)
            self.relief_answer_id = plan.assistant_id
            self.engine.arm_relief(self.clock())
        else:
            marker = self.timeline.add_marker(t_ms, "answer", "Answer", plan.assistant_id)
        out.append({"type": "marker", "marker": marker})
        self.notify(*out)
        self.touch()
        return {
            "assistant_message_id": plan.assistant_id,
            "finish_reason": finish_reason,
            "ttft_ms": ttft_ms,
            "elapsed_ms": elapsed_ms,
            "model": model,
            "created": t_ms,
        }

    def abort_chat(self, plan: ChatPlan) -> None:
        """Nothing of a failed/cancelled request is kept; offers attached to the
        never-committed answer are expired."""
        if self._chat_plan is plan:
            self._chat_plan = None
        if plan.epoch != self.epoch:
            return
        if self.current_answer_id == plan.assistant_id:
            latest = self._latest_answer()
            self.current_answer_id = latest["id"] if latest else None
            updates = []
            for ev in self.events.values():
                if ev.get("answer_id") == plan.assistant_id and ev["status"] == "offered":
                    ev["status"] = "expired"
                    updates.append({"type": "event_update", "event": ev})
            self.notify(*updates)

    # ------------------------------------------------------------------ reset / snapshots
    def reset(self) -> int:
        self.epoch += 1
        if self._chat_plan is not None:
            self._chat_plan.cancel_reason.append("reset")
            self._chat_plan.cancel.set()
            self._chat_plan = None
        self._chat_generation += 1
        self.engine.reset()
        self.proxy.reset()
        self.timeline.clear()
        self.messages.clear()
        self.events.clear()
        self._event_mono.clear()
        self._chain_adaptations.clear()
        self.current_answer_id = None
        self.relief_answer_id = None
        self.sim_enabled = False
        self.touch()
        self.notify({"type": "reset", "epoch": self.epoch}, self.snapshot_message())
        return self.epoch

    def public_messages(self) -> list[dict[str, Any]]:
        return [dict(m) for m in self.messages]

    def snapshot_message(self) -> dict[str, Any]:
        last = self.engine.last_state
        return {
            "type": "snapshot",
            "epoch": self.epoch,
            "events": list(self.events.values()),
            "timeline": self.timeline.snapshot(now_ms(), self.settings.timeline_snapshot_points),
            "engine": None if last is None else last.to_public(self.engine.cfg),
            "sim": {"enabled": self.sim_enabled},
            "calibrated": self.proxy.baseline is not None,
        }

    def state_payload(self, boot_id: str) -> dict[str, Any]:
        snap = self.snapshot_message()
        return {
            "session_id": self.id,
            "boot_id": boot_id,
            "epoch": self.epoch,
            "subject": self.subject,
            "messages": self.public_messages(),
            "events": snap["events"],
            "timeline": snap["timeline"],
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
