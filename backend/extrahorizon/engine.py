"""State engine — the ONE place that decides whether ExtraHorizon adapts.

Input : a stream of observations (confusion proxy in [0, 1], or "not measurable").
Output: the smoothed value the UI displays + discrete events.

Rules (all durations are wall-clock seconds from the injected clock, never frame
counts):

* not measurable (no face, several faces, poor quality, calibrating, camera off,
  or a gap longer than ``max_gap_s`` between observations) → smoothed = None and
  the hold timer is reset. Unknown is never mapped to "neutral" or "confused".
* smoothing: EMA with a time-based coefficient
  ``a = 1 - (1 - alpha) ** (dt * reference_fps)`` — identical to the classic
  per-frame ``alpha`` at ``reference_fps`` and correct at any real frame rate.
* trigger: smoothed > threshold continuously for ≥ hold_s → one
  ``possible_confusion`` event, then a cooldown during which the hold timer does
  not accumulate (a fresh full hold is needed after it).
* one event per episode: after an event the engine is *disarmed* until the smoothed
  value drops below ``rearm_threshold`` or a new answer arrives (``rearm()``), so a
  face that simply stays tense is not nagged every cooldown period.
* relief: after an adapted answer, if smoothed stays < relief_threshold for
  ≥ relief_hold_s within relief_window_s, emit one informational
  ``signal_decreased`` event. Nothing is claimed unless it was measured.

The module is pure (no I/O, no asyncio) so every rule is unit-tested directly.
"""

from __future__ import annotations

import math
import secrets
from dataclasses import dataclass
from typing import Any

OK = "ok"
UNKNOWN = "unknown"
CALIBRATING = "calibrating"

POSSIBLE_CONFUSION = "possible_confusion"
SIGNAL_DECREASED = "signal_decreased"


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


@dataclass(frozen=True)
class EngineConfig:
    alpha: float = 0.2
    reference_fps: float = 10.0
    threshold: float = 0.65
    hold_s: float = 2.0
    cooldown_s: float = 15.0
    max_gap_s: float = 0.75
    relief_threshold: float = 0.45
    relief_hold_s: float = 2.0
    relief_window_s: float = 60.0
    rearm_threshold: float = 0.55

    @classmethod
    def from_settings(cls, s: Any) -> "EngineConfig":
        return cls(
            alpha=s.ema_alpha,
            reference_fps=s.ema_reference_fps,
            threshold=s.threshold,
            hold_s=s.hold_s,
            cooldown_s=s.cooldown_s,
            max_gap_s=s.max_gap_s,
            relief_threshold=s.relief_threshold,
            relief_hold_s=s.relief_hold_s,
            relief_window_s=s.relief_window_s,
            rearm_threshold=s.rearm_threshold,
        )

    def rule(self) -> dict[str, float]:
        return {
            "alpha": self.alpha,
            "reference_fps": self.reference_fps,
            "threshold": self.threshold,
            "hold_s": self.hold_s,
            "cooldown_s": self.cooldown_s,
        }


@dataclass(frozen=True)
class Observation:
    t: float  # seconds, monotonic clock
    value: float | None  # raw confusion proxy in [0, 1]; None when not measurable
    status: str = OK  # ok | unknown | calibrating
    reason: str | None = None
    source: str = "camera"  # camera | simulation


@dataclass(frozen=True)
class EngineEvent:
    id: str
    kind: str
    t: float
    source: str
    smoothed: float
    raw: float
    held_s: float


@dataclass(frozen=True)
class EngineState:
    t: float
    source: str
    status: str
    reason: str | None
    raw: float | None
    smoothed: float | None
    above: bool
    held_s: float
    cooldown_left_s: float
    armed: bool = True

    def to_public(self, cfg: EngineConfig) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "reason": self.reason,
            "raw": _r(self.raw),
            "smoothed": _r(self.smoothed),
            "above": self.above,
            "held_s": round(self.held_s, 2),
            "hold_s": cfg.hold_s,
            "threshold": cfg.threshold,
            "cooldown_left_s": round(self.cooldown_left_s, 1),
            "armed": self.armed,
        }


def _r(x: float | None, nd: int = 3) -> float | None:
    return None if x is None else round(x, nd)


class StateEngine:
    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg
        self.reset()

    # ------------------------------------------------------------------ control
    def reset(self) -> None:
        self._smoothed: float | None = None
        self._last_ok_t: float | None = None
        self._source: str | None = None
        self._above_since: float | None = None
        self._cooldown_until: float | None = None
        self._relief_until: float | None = None
        self._relief_since: float | None = None
        self._armed = True
        self.last_state: EngineState | None = None

    def rearm(self) -> None:
        """A new answer starts a new episode: the next sustained rise may fire again."""
        self._armed = True

    def arm_relief(self, t: float) -> None:
        """Start watching for an observed decrease (called after an adapted answer)."""
        self._relief_until = t + self.cfg.relief_window_s
        self._relief_since = None

    def cooldown_left(self, t: float) -> float:
        if self._cooldown_until is None:
            return 0.0
        return max(0.0, self._cooldown_until - t)

    # ------------------------------------------------------------------ update
    def update(self, obs: Observation) -> tuple[EngineState, list[EngineEvent]]:
        cfg = self.cfg
        t = obs.t
        events: list[EngineEvent] = []

        # switching between camera and labelled simulation never carries state over
        if self._source is not None and obs.source != self._source:
            self._clear_accumulation()
        self._source = obs.source

        value = obs.value
        measurable = obs.status == OK and value is not None and math.isfinite(value)
        if not measurable:
            self._clear_accumulation()
            status = obs.status if obs.status != OK else UNKNOWN
            state = EngineState(
                t=t,
                source=obs.source,
                status=status,
                reason=obs.reason or ("no_value" if status == UNKNOWN else None),
                raw=None,
                smoothed=None,
                above=False,
                held_s=0.0,
                cooldown_left_s=self.cooldown_left(t),
                armed=self._armed,
            )
            self.last_state = state
            return state, events

        value = min(1.0, max(0.0, float(value)))
        gap = None if self._last_ok_t is None else t - self._last_ok_t
        if self._smoothed is None or gap is None or gap < 0 or gap > cfg.max_gap_s:
            # (re)start after unknown / a data gap: accumulation starts from scratch
            self._clear_accumulation()
            self._smoothed = value
        elif gap > 0:
            a = 1.0 - (1.0 - cfg.alpha) ** (gap * cfg.reference_fps)
            self._smoothed += a * (value - self._smoothed)
        self._last_ok_t = t
        s = self._smoothed

        if not self._armed and s < cfg.rearm_threshold:
            self._armed = True  # the episode ended: the signal really came down
        in_cooldown = self._cooldown_until is not None and t < self._cooldown_until
        above = s > cfg.threshold
        if above and not in_cooldown and self._armed:
            if self._above_since is None:
                self._above_since = t
        else:
            self._above_since = None
        held = t - self._above_since if self._above_since is not None else 0.0

        if self._above_since is not None and held >= cfg.hold_s:
            events.append(
                EngineEvent(new_id("ev"), POSSIBLE_CONFUSION, t, obs.source, s, value, held)
            )
            self._cooldown_until = t + cfg.cooldown_s
            self._above_since = None
            self._armed = False
            # a new confusion episode cancels a pending "decrease" watch
            self._relief_until = None
            self._relief_since = None

        if self._relief_until is not None:
            if t > self._relief_until:
                self._relief_until = None
                self._relief_since = None
            elif s < cfg.relief_threshold:
                if self._relief_since is None:
                    self._relief_since = t
                elif t - self._relief_since >= cfg.relief_hold_s:
                    events.append(
                        EngineEvent(
                            new_id("ev"), SIGNAL_DECREASED, t, obs.source, s, value, t - self._relief_since
                        )
                    )
                    self._relief_until = None
                    self._relief_since = None
            else:
                self._relief_since = None

        state = EngineState(
            t=t,
            source=obs.source,
            status=OK,
            reason=None,
            raw=value,
            smoothed=s,
            above=above,
            held_s=held if self._above_since is not None else 0.0,
            cooldown_left_s=self.cooldown_left(t),
            armed=self._armed,
        )
        self.last_state = state
        return state, events

    def _clear_accumulation(self) -> None:
        self._smoothed = None
        self._last_ok_t = None
        self._above_since = None
        self._relief_since = None
