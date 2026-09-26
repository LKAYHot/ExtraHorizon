"""Per-person calibration of the facial-expression estimate.

Why: facial-expression classifiers are biased per person, camera and light. A relaxed face
often reads "angry" or "unimpressed" (heavy brows, squinting at a screen, a webcam below
eye level — measured here: a relaxed face read *anger 0.94–0.97*), and a slightly lowered
head tips it further. ExtraHorizon therefore learns what *this* learner's relaxed face
looks like and measures expressions relative to it:

1. **Baseline** — ~2.5 s of a relaxed face (medians of the class logits, valence/arousal,
   the 52 MediaPipe blendshapes and the head pose); frames while talking or with the head
   turned are skipped, the median absorbs a passing smile.
2. **Bias correction** — logits are shifted so that the baseline face maps to a typical
   neutral distribution (a prior correction in logit space); valence/arousal likewise. A
   real expression still moves the logits away from the baseline and shows up.
3. **Facial-action evidence** — every non-neutral class must be backed by the matching
   change of the blendshapes relative to the baseline (FACS-style action units: anger =
   brows down + lids tight + lips pressed; happiness = smile + cheek raise; surprise =
   brows up + eyes wide; …). Without that evidence the class is damped toward neutral —
   a small brow shift no longer reads as anger.
4. **Pose weighting** — the appearance model is sensitive to head pitch/yaw; frames far
   from the calibration pose count less (the estimate holds instead of jumping) and need
   more facial evidence.
5. **Slow adaptation** — while the face is clearly relaxed, the baseline follows lighting
   and posture drift (τ ≈ 60 s); it never absorbs a visible expression.

Pure logic (NumPy only), clock passed in — unit-tested directly.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..vision.types import EMOTIONS, EmotionReading

NEUTRAL = EMOTIONS.index("neutral")

# sensitivity presets: evidence-threshold scale, how much the classifier alone may push a
# class without facial evidence, and the engine's smoothing / switching rules
SENSITIVITY: dict[str, dict[str, float]] = {
    "calm": {"scale": 1.35, "floor": 0.20, "min_prob": 0.50, "alpha": 0.15, "hold": 1.6, "margin": 0.15},
    "balanced": {"scale": 1.00, "floor": 0.30, "min_prob": 0.42, "alpha": 0.20, "hold": 1.2, "margin": 0.12},
    "expressive": {"scale": 0.75, "floor": 0.45, "min_prob": 0.32, "alpha": 0.30, "hold": 0.8, "margin": 0.08},
}

# baseline-relative activation (sum of weighted blendshape increases) that starts / fully backs a class
THRESHOLDS: dict[str, tuple[float, float]] = {
    "happiness": (0.08, 0.35),
    "surprise": (0.08, 0.35),
    "anger": (0.10, 0.40),
    "sadness": (0.06, 0.30),
    "fear": (0.08, 0.35),
    "disgust": (0.05, 0.25),
    "contempt": (0.05, 0.20),
}

# the distribution a relaxed face should map to
P_REF = np.full(len(EMOTIONS), 0.30 / (len(EMOTIONS) - 1))
P_REF[NEUTRAL] = 0.70
Z_REF = np.log(P_REF) - np.log(P_REF).mean()
VA_REF = (0.0, -0.1)


def smoothstep(lo: float, hi: float, x: float) -> float:
    if x <= lo:
        return 0.0
    if x >= hi:
        return 1.0
    u = (x - lo) / (hi - lo)
    return u * u * (3 - 2 * u)


def _softmax(z: np.ndarray) -> np.ndarray:
    e = np.exp(z - z.max())
    return e / e.sum()


class _Delta:
    """Baseline-relative blendshape activations (increases only)."""

    def __init__(self, bs: dict[str, float], base: dict[str, float]) -> None:
        self.bs, self.base = bs, base

    def d(self, k: str) -> float:
        return max(0.0, self.bs.get(k, 0.0) - self.base.get(k, 0.0))

    def pair(self, k: str) -> float:
        return (self.d(k + "Left") + self.d(k + "Right")) / 2

    def pmax(self, k: str) -> float:
        return max(self.d(k + "Left"), self.d(k + "Right"))

    def asym(self, k: str) -> float:
        now = abs(self.bs.get(k + "Left", 0.0) - self.bs.get(k + "Right", 0.0))
        was = abs(self.base.get(k + "Left", 0.0) - self.base.get(k + "Right", 0.0))
        return max(0.0, now - was)


def evidence(bs: dict[str, float], base: dict[str, float]) -> dict[str, float]:
    """FACS-style facial-action evidence for each non-neutral class (0 = none)."""
    x = _Delta(bs, base)
    return {
        "happiness": x.pmax("mouthSmile") + 0.3 * x.pair("cheekSquint"),
        "surprise": max(x.d("browInnerUp"), x.pair("browOuterUp")) + 0.5 * x.pmax("eyeWide") + 0.2 * x.d("jawOpen"),
        "anger": x.pair("browDown") + 0.4 * x.pair("eyeSquint") + 0.4 * x.pmax("mouthPress") + 0.3 * x.pmax("noseSneer"),
        "sadness": x.pmax("mouthFrown") + 0.6 * x.d("browInnerUp") + 0.3 * x.d("mouthShrugLower"),
        "fear": 0.7 * x.d("browInnerUp") + 0.7 * x.pmax("eyeWide") + 0.6 * x.pmax("mouthStretch"),
        "disgust": x.pmax("noseSneer") + 0.8 * x.pmax("mouthUpperUp"),
        "contempt": x.asym("mouthSmile") + 0.6 * x.asym("mouthDimple"),
    }


def facial_actions(bs: dict[str, float], base: dict[str, float], dpitch: float = 0.0, dyaw: float = 0.0) -> list[str]:
    """What is visibly different from the relaxed face, in plain words (for the tutor)."""
    x = _Delta(bs, base)
    out = []
    smiling = x.pmax("mouthSmile") >= 0.25
    if smiling:
        out.append("smiling")
    if x.pair("browDown") >= 0.20:
        out.append("frowning, brows pulled down")
    if max(x.d("browInnerUp"), x.pair("browOuterUp")) >= 0.20:
        out.append("eyebrows raised")
    if x.pmax("eyeWide") >= 0.20:
        out.append("eyes wide open")
    if x.pair("eyeSquint") >= 0.25 and not smiling:
        out.append("squinting")
    if x.pmax("mouthPress") >= 0.20:
        out.append("lips pressed together")
    if x.pmax("mouthFrown") >= 0.15:
        out.append("corners of the mouth turned down")
    if x.pmax("noseSneer") >= 0.15:
        out.append("nose wrinkled")
    if x.asym("mouthSmile") >= 0.12 and not smiling:
        out.append("a one-sided smirk")
    if dpitch >= 15:
        out.append("looking down")
    elif dpitch <= -15:
        out.append("head tilted back")
    if abs(dyaw) >= 20:
        out.append("looking away from the screen")
    return out


@dataclass
class Baseline:
    z: np.ndarray  # centred logits of the relaxed face
    valence: float
    arousal: float
    bs: dict[str, float]
    pitch: float
    yaw: float
    frames: int


@dataclass
class Corrected:
    probs: tuple[float, ...]
    valence: float | None
    arousal: float | None
    weight: float  # 0.1 … 1: how much this frame may move the smoothed estimate
    actions: tuple[str, ...]
    evidence: dict[str, float]


def pose_weight(dpitch: float, dyaw: float) -> float:
    """Full weight within ±6° pitch / ±8° yaw of the calibration pose, ~0.1 at 24° / 30°."""
    wp = 1.0 - max(0.0, abs(dpitch) - 6.0) / 18.0
    wy = 1.0 - max(0.0, abs(dyaw) - 8.0) / 22.0
    return max(0.1, min(1.0, wp)) * max(0.1, min(1.0, wy))


class Calibrator:
    """One per session. ``observe`` returns ``None`` while the baseline is being collected."""

    def __init__(self, seconds: float = 2.5, min_frames: int = 15, adapt_tau_s: float = 60.0,
                 sensitivity: str = "balanced", correction: float = 0.9, max_shift: float = 6.0) -> None:
        self.seconds = seconds
        self.min_frames = min_frames
        self.adapt_tau_s = adapt_tau_s
        self.correction = correction
        self.max_shift = max_shift
        self.level = sensitivity if sensitivity in SENSITIVITY else "balanced"
        self.baseline: Baseline | None = None
        self._samples: list[tuple[np.ndarray, float, float, dict[str, float], float, float]] = []
        self._collected_s = 0.0
        self._waited_s = 0.0
        self._last_t: float | None = None
        self._recent_actions: deque[tuple[str, ...]] = deque(maxlen=8)

    # ------------------------------------------------------------------ state
    @property
    def ready(self) -> bool:
        return self.baseline is not None

    @property
    def progress(self) -> float:
        if self.baseline is not None:
            return 1.0
        return min(1.0, self._collected_s / self.seconds, len(self._samples) / self.min_frames)

    def public(self) -> dict[str, Any]:
        return {"state": "ready" if self.ready else "collecting", "progress": round(self.progress, 2),
                "sensitivity": self.level}

    def restart(self) -> None:
        self.baseline = None
        self._samples.clear()
        self._collected_s = 0.0
        self._waited_s = 0.0
        self._last_t = None
        self._recent_actions.clear()

    def set_sensitivity(self, level: str) -> None:
        if level in SENSITIVITY:
            self.level = level

    @property
    def preset(self) -> dict[str, float]:
        return SENSITIVITY[self.level]

    # ------------------------------------------------------------------ per frame
    def observe(self, t: float, reading: EmotionReading, bs: dict[str, float] | None,
                pose: tuple[float, float, float] | None, speaking: bool = False) -> Corrected | None:
        z = np.asarray(reading.logits if reading.logits is not None else np.log(np.maximum(reading.probs, 1e-9)),
                       dtype=np.float64)
        z = z - z.mean()
        bs = bs or {}
        yaw, pitch = (pose[0], pose[1]) if pose else (0.0, 0.0)
        dt = 0.0 if self._last_t is None else min(0.5, max(0.0, t - self._last_t))
        self._last_t = t
        if self.baseline is None:
            self._collect(z, reading, bs, pitch, yaw, dt, speaking)
            if self.baseline is None:
                return None  # still learning the relaxed face
        return self._correct(z, reading, bs, pitch, yaw, dt, speaking)

    def _collect(self, z: np.ndarray, r: EmotionReading, bs: dict[str, float], pitch: float, yaw: float,
                 dt: float, speaking: bool) -> None:
        # a talking mouth or a turned head is not the resting face; the median over the window
        # absorbs a passing smile. If the face never settles (8 s), take it as it is.
        self._waited_s += dt
        steady = bs.get("jawOpen", 0.0) < 0.35 and abs(pitch) < 25 and abs(yaw) < 25 and not speaking
        if not steady and self._waited_s < 8.0:
            return
        self._samples.append((z, r.valence if r.valence is not None else 0.0,
                              r.arousal if r.arousal is not None else 0.0, dict(bs), pitch, yaw))
        self._collected_s += dt
        if self._collected_s >= self.seconds and len(self._samples) >= self.min_frames:
            zs = np.median(np.stack([s[0] for s in self._samples]), axis=0)
            keys = set().union(*(s[3].keys() for s in self._samples))
            self.baseline = Baseline(
                z=zs - zs.mean(),
                valence=float(np.median([s[1] for s in self._samples])),
                arousal=float(np.median([s[2] for s in self._samples])),
                bs={k: float(np.median([s[3].get(k, 0.0) for s in self._samples])) for k in keys},
                pitch=float(np.median([s[4] for s in self._samples])),
                yaw=float(np.median([s[5] for s in self._samples])),
                frames=len(self._samples),
            )
            self._samples.clear()

    def _correct(self, z: np.ndarray, r: EmotionReading, bs: dict[str, float], pitch: float, yaw: float,
                 dt: float, speaking: bool) -> Corrected:
        b = self.baseline
        assert b is not None
        pre = self.preset
        bias = np.clip(b.z - Z_REF, -self.max_shift, self.max_shift)
        p = _softmax(z - self.correction * bias)
        dpitch, dyaw = pitch - b.pitch, yaw - b.yaw
        w = pose_weight(dpitch, dyaw)
        ev = evidence(bs, b.bs) if bs else {}
        if ev:
            floor = pre["floor"] * (0.4 + 0.6 * w)  # far from the calibration pose: evidence matters more
            removed = 0.0
            for name, (lo, hi) in THRESHOLDS.items():
                i = EMOTIONS.index(name)
                g = floor + (1.0 - floor) * smoothstep(lo * pre["scale"], hi * pre["scale"], ev[name])
                removed += p[i] * (1.0 - g)
                p[i] *= g
            p[NEUTRAL] += removed
        v = a = None
        if r.valence is not None:
            v = float(np.clip(r.valence - self.correction * (b.valence - VA_REF[0]), -1.0, 1.0))
        if r.arousal is not None:
            a = float(np.clip(r.arousal - self.correction * (b.arousal - VA_REF[1]), -1.0, 1.0))
        acts = tuple(facial_actions(bs, b.bs, dpitch, dyaw)) if bs else ()
        self._recent_actions.append(acts)
        weight = w * (0.5 if speaking else 1.0)  # a talking mouth is not an expression
        self._adapt(z, r, bs, pitch, yaw, dt, p, ev, w, speaking)
        return Corrected(tuple(float(x) for x in p), v, a, max(0.1, weight), self.steady_actions(), ev)

    def steady_actions(self) -> tuple[str, ...]:
        """Actions present in at least half of the last few frames (no single-frame noise)."""
        n = len(self._recent_actions)
        if not n:
            return ()
        counts: dict[str, int] = {}
        for acts in self._recent_actions:
            for a in acts:
                counts[a] = counts.get(a, 0) + 1
        order = [a for acts in self._recent_actions for a in acts]
        seen: list[str] = []
        for a in order:
            if counts[a] * 2 >= n and a not in seen:
                seen.append(a)
        return tuple(seen)

    def _adapt(self, z: np.ndarray, r: EmotionReading, bs: dict[str, float], pitch: float, yaw: float, dt: float,
               p: np.ndarray, ev: dict[str, float], w: float, speaking: bool) -> None:
        """Follow slow drift (light, posture) while the face is clearly relaxed."""
        b = self.baseline
        if b is None or dt <= 0 or speaking or w < 0.8 or p[NEUTRAL] < 0.65:
            return
        if ev and any(ev[name] >= lo for name, (lo, _) in THRESHOLDS.items()):
            return
        eta = min(1.0, dt / self.adapt_tau_s)
        b.z = b.z + eta * (z - b.z)
        b.z = b.z - b.z.mean()
        for k, val in bs.items():
            b.bs[k] = b.bs.get(k, val) + eta * (val - b.bs.get(k, val))
        b.pitch += eta * (pitch - b.pitch)
        b.yaw += eta * (yaw - b.yaw)
        if r.valence is not None:
            b.valence += eta * (r.valence - b.valence)
        if r.arousal is not None:
            b.arousal += eta * (r.arousal - b.arousal)
