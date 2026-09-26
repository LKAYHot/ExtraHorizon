"""Emotion engine — per-session smoothing of facial-expression estimates.

Input : one observation per analysed frame (8 class probabilities + valence/arousal),
        or "not measurable" (no face, several faces, poor quality, camera off, …).
Output: the smoothed distribution the UI shows, a *stable* dominant emotion, change
        events, a short history of segments, and a plain-English description that is
        added to the LLM prompt.

Rules (durations are wall-clock seconds from the injected clock, never frame counts):

* smoothing: time-based EMA ``a = 1 - (1 - alpha) ** (dt * reference_fps)`` per class;
* unknown (or a gap longer than ``max_gap_s``) → no distribution, no dominant emotion,
  smoothing restarts. Unknown is never reported as "neutral";
* the dominant emotion switches only after the new leader has led for
  ``switch_hold_s`` by at least ``switch_margin`` (no flicker between close classes);
* the description uses words only — no percentages or other digits (no false precision).

Pure logic: no I/O, clock injected — unit-tested directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..vision.types import EMOTIONS
from .calibration import actions_for

OK = "ok"
UNKNOWN = "unknown"

LABELS = {
    "anger": "angry",
    "contempt": "unimpressed",
    "disgust": "disgusted",
    "fear": "anxious",
    "happiness": "happy",
    "neutral": "neutral",
    "sadness": "sad",
    "surprise": "surprised",
}
NOUNS = {
    "anger": "anger",
    "contempt": "contempt",
    "disgust": "disgust",
    "fear": "anxiety",
    "happiness": "happiness",
    "neutral": "calm",
    "sadness": "sadness",
    "surprise": "surprise",
}


@dataclass(frozen=True)
class EmotionConfig:
    alpha: float = 0.20
    reference_fps: float = 10.0
    max_gap_s: float = 1.0
    switch_hold_s: float = 1.2
    switch_margin: float = 0.12
    history_s: float = 60.0
    min_prob: float = 0.42  # a non-neutral expression must reach this to be reported

    @classmethod
    def from_settings(cls, s: Any, level: str | None = None) -> "EmotionConfig":
        from .calibration import SENSITIVITY

        pre = SENSITIVITY.get(level or s.emotion_sensitivity, SENSITIVITY["balanced"])
        return cls(
            alpha=pre["alpha"],
            reference_fps=s.emotion_reference_fps,
            max_gap_s=s.emotion_max_gap_s,
            switch_hold_s=pre["hold"],
            switch_margin=pre["margin"],
            history_s=s.emotion_history_s,
            min_prob=pre["min_prob"],
        )


@dataclass(frozen=True)
class EmotionObservation:
    t: float
    probs: tuple[float, ...] | None  # over EMOTIONS; None when not measurable
    valence: float | None = None
    arousal: float | None = None
    status: str = OK
    reason: str | None = None
    source: str = "camera"  # camera | simulation
    weight: float = 1.0  # how far this frame may move the smoothed estimate (pose, talking)
    actions: tuple[str, ...] = ()  # visible facial actions relative to the relaxed face


@dataclass(frozen=True)
class EmotionChange:
    t: float
    previous: str | None
    current: str
    prob: float
    source: str


@dataclass
class Segment:
    emotion: str
    start: float
    end: float
    source: str = "camera"  # a simulated segment never feeds a camera description


@dataclass(frozen=True)
class EmotionState:
    t: float
    source: str
    status: str
    reason: str | None
    probs: tuple[float, ...] | None
    valence: float | None
    arousal: float | None
    dominant: str | None
    dominant_prob: float | None
    dominant_for_s: float

    def to_public(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "reason": self.reason,
            "probs": None if self.probs is None else {k: round(v, 3) for k, v in zip(EMOTIONS, self.probs)},
            "valence": None if self.valence is None else round(self.valence, 3),
            "arousal": None if self.arousal is None else round(self.arousal, 3),
            "dominant": self.dominant,
            "dominant_prob": None if self.dominant_prob is None else round(self.dominant_prob, 3),
            "dominant_for_s": round(self.dominant_for_s, 1),
        }


def _duration_words(seconds: float) -> str:
    if seconds < 6:
        return "a few seconds"
    if seconds < 20:
        return "about ten seconds"
    if seconds < 45:
        return "about half a minute"
    if seconds < 90:
        return "about a minute"
    return "a few minutes"


class EmotionEngine:
    def __init__(self, cfg: EmotionConfig) -> None:
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self._p: list[float] | None = None
        self._v: float | None = None
        self._a: float | None = None
        self._last_ok_t: float | None = None
        self._source: str | None = None
        self._dominant: str | None = None
        self._dominant_since: float | None = None
        self._candidate: str | None = None
        self._candidate_since: float | None = None
        self._actions: tuple[str, ...] = ()
        self.segments: list[Segment] = []
        self.last_state: EmotionState | None = None

    # ------------------------------------------------------------------ update
    def update(self, obs: EmotionObservation) -> tuple[EmotionState, list[EmotionChange]]:
        cfg = self.cfg
        t = obs.t
        changes: list[EmotionChange] = []
        if self._source is not None and obs.source != self._source:
            self._end_run(t)
        self._source = obs.source

        measurable = obs.status == OK and obs.probs is not None and len(obs.probs) == len(EMOTIONS)
        if not measurable:
            self._end_run(t)
            state = EmotionState(
                t=t, source=obs.source, status=UNKNOWN if obs.status == OK else obs.status,
                reason=obs.reason or "no_value", probs=None, valence=None, arousal=None,
                dominant=None, dominant_prob=None, dominant_for_s=0.0,
            )
            self.last_state = state
            return state, changes

        probs = [max(0.0, float(x)) for x in obs.probs]  # type: ignore[union-attr]
        total = sum(probs) or 1.0
        probs = [x / total for x in probs]
        gap = None if self._last_ok_t is None else t - self._last_ok_t
        self._actions = obs.actions
        if self._p is None or gap is None or gap < 0 or gap > cfg.max_gap_s:
            self._end_run(t)
            self._actions = obs.actions
            self._p = probs
            self._v, self._a = obs.valence, obs.arousal
            self._set_dominant(self._leader(), t, changes, obs.source)
        else:
            a = 1.0 - (1.0 - cfg.alpha) ** (gap * cfg.reference_fps) if gap > 0 else 0.0
            a *= min(1.0, max(0.05, obs.weight))  # an unreliable frame (pose, talking) moves it less
            self._p = [p + a * (x - p) for p, x in zip(self._p, probs)]
            if obs.valence is not None:
                self._v = obs.valence if self._v is None else self._v + a * (obs.valence - self._v)
            if obs.arousal is not None:
                self._a = obs.arousal if self._a is None else self._a + a * (obs.arousal - self._a)
            self._maybe_switch(t, changes, obs.source)
        self._last_ok_t = t

        p = self._p
        dom = self._dominant
        state = EmotionState(
            t=t, source=obs.source, status=OK, reason=None, probs=tuple(p),
            valence=self._v, arousal=self._a, dominant=dom,
            dominant_prob=p[EMOTIONS.index(dom)] if dom else None,
            dominant_for_s=(t - self._dominant_since) if self._dominant_since is not None else 0.0,
        )
        self.last_state = state
        return state, changes

    def _leader(self) -> str:
        """The strongest class — but an expression is reported only once it is clearly there
        (≥ ``min_prob``); anything weaker counts as neutral."""
        assert self._p is not None
        lead = max(range(len(EMOTIONS)), key=lambda i: self._p[i])  # type: ignore[index]
        if EMOTIONS[lead] != "neutral" and self._p[lead] < self.cfg.min_prob:
            return "neutral"
        return EMOTIONS[lead]

    def _maybe_switch(self, t: float, changes: list[EmotionChange], source: str) -> None:
        assert self._p is not None
        leader = self._leader()
        if leader == self._dominant:
            self._candidate = self._candidate_since = None
            return
        if leader != self._candidate:
            self._candidate, self._candidate_since = leader, t
            return
        current_p = self._p[EMOTIONS.index(self._dominant)] if self._dominant else 0.0
        lead_p = self._p[EMOTIONS.index(leader)]
        held = t - (self._candidate_since or t)
        # back to neutral once the current expression faded below the floor; otherwise the
        # newcomer must lead by the margin
        faded = leader == "neutral" and current_p < self.cfg.min_prob
        if held >= self.cfg.switch_hold_s and (faded or lead_p - current_p >= self.cfg.switch_margin):
            self._set_dominant(leader, t, changes, source)

    def _set_dominant(self, emotion: str, t: float, changes: list[EmotionChange], source: str) -> None:
        if self._dominant is not None and self._dominant_since is not None:
            self._push_segment(self._dominant, self._dominant_since, t)
        previous = self._dominant
        self._dominant, self._dominant_since = emotion, t
        self._candidate = self._candidate_since = None
        if previous != emotion:
            prob = self._p[EMOTIONS.index(emotion)] if self._p else 0.0
            changes.append(EmotionChange(t, previous, emotion, prob, source))

    def _end_run(self, t: float) -> None:
        """Unknown / gap / source switch: close the running segment, forget smoothing."""
        if self._dominant is not None and self._dominant_since is not None:
            self._push_segment(self._dominant, self._dominant_since, t)
        self._p = self._v = self._a = None
        self._last_ok_t = None
        self._dominant = self._dominant_since = None
        self._candidate = self._candidate_since = None
        self._actions: tuple[str, ...] = ()

    def _push_segment(self, emotion: str, start: float, end: float) -> None:
        if end - start < 0.3:
            return
        source = self._source or "camera"
        last = self.segments[-1] if self.segments else None
        if last and last.emotion == emotion and last.source == source and start - last.end < 1.5:
            last.end = end
        else:
            self.segments.append(Segment(emotion, start, end, source))
        cutoff = end - self.cfg.history_s
        self.segments = [s for s in self.segments if s.end >= cutoff][-20:]

    # ------------------------------------------------------------------ prompt description
    def describe(self, now: float) -> dict[str, Any]:
        """Plain-English context for the LLM (words only, no digits) + a UI summary."""
        st = self.last_state
        fresh = st is not None and st.status == OK and st.probs is not None and now - st.t <= self.cfg.max_gap_s * 2
        if not fresh:
            reason = st.reason if st is not None else "no_camera"
            return {
                "available": False,
                "reason": reason,
                "source": st.source if st else None,
                "text": "Camera emotion estimate: not available right now (no single clear face in view).",
            }
        assert st is not None and st.probs is not None
        ranked = sorted(zip(EMOTIONS, st.probs), key=lambda kv: -kv[1])
        main, p_main = ranked[0]
        if st.dominant:
            main, p_main = st.dominant, st.probs[EMOTIONS.index(st.dominant)]
        strength = "clearly" if p_main >= 0.6 else "mostly" if p_main >= 0.4 else "somewhat"
        if main == "neutral":
            parts = ["The learner looks relaxed, a neutral expression"]
        else:
            parts = [f"The learner looks {strength} {LABELS[main]}"]
        second = next(((k, v) for k, v in ranked if k != main), None)
        if second and second[1] >= 0.2 and second[0] != "neutral":
            parts.append(f", with a bit of {NOUNS[second[0]]}")
        text = "".join(parts) + "."
        visible = actions_for(self._actions, main)  # only what fits the expression it reports
        if visible:
            text += f" Visible right now: {'; '.join(visible)}."
        mood = []
        if st.valence is not None:
            mood.append("positive" if st.valence > 0.25 else "negative" if st.valence < -0.25 else "neutral")
        if st.arousal is not None:
            energy = "high energy" if st.arousal > 0.35 else "low energy" if st.arousal < -0.15 else "moderate energy"
            mood.append(energy)
        if mood:
            text += f" Overall mood: {', '.join(mood)}."
        held = st.dominant_for_s
        # the running one is not a segment yet; never mix simulated and camera history
        previous = [s for s in self.segments if s.emotion != main and s.source == st.source]
        if previous:
            before = previous[-1]
            ago = st.t - before.end
            text += f" Before that ({_duration_words(ago)} ago) they looked {LABELS[before.emotion]}."
        elif held >= 20:
            text += f" This has been steady for {_duration_words(held)}."
        return {
            "available": True,
            "dominant": main,
            "strength": strength,
            "source": st.source,
            "text": text,
        }
