"""Per-person calibration of the facial-expression estimate.

Why: expression classifiers are biased per person, camera and light. Measured on a real
learner (laptop webcam below eye level, heavy brows, a headset): all five EmotiEffLib models
read the *relaxed* face as anger (0.69–0.97). Their real angry faces read anger 0.98 too — what
changed was that **neutral dropped** (neutral margin −4.5 → −8.5) while the anger score barely
moved. Shifting every class toward a reference distribution therefore erased that person's
anger, and MediaPipe's brow blendshapes (brow-down 0.4 at rest, ~0 in a snarl) were too
unreliable to demand as evidence. So:

1. **Baseline** — ~2.5 s of a relaxed face: medians of the classifier logits, valence/arousal,
   blendshapes and head pose; frames while talking, with the jaw open or the head turned are
   skipped, the median absorbs a passing smile.
2. **Neutral vs. an expression, relative to the relaxed face** — the relaxed face reads neutral
   with the preset's ``p_ref`` (0.9 for Balanced; a very neutral face keeps half of its extra
   neutrality). The *intensity* of an expression is how far the classes the face shows now have
   moved against neutral since the relaxed face (log-odds gains weighted by their current
   probability): a stern face that snarls (anger gains as neutral drops) and a stern face that
   smiles (happiness replaces anger — the neutral share hardly moves) both count, while
   low-probability noise barely does.
3. **Which expression** — the classifier's reading of the face *now* among the non-neutral
   classes (absolute appearance: a stern face that snarls is angry, not "disgusted"), limited
   to classes that gained on neutral since the relaxed face (a stern face that smiles is happy,
   not angry) and softly weighted by missing hallmark facial actions (disgust without a raised
   upper lip or wrinkled nose, happiness without a smile, …). This only moves probability
   between expressions — never into neutral.
4. **Pose and talking** — frames far from the calibration pose or while the learner talks carry
   less evidence: a small neutral bonus and a lower weight for the smoothing.
5. **Slow adaptation** — while the classifier reads the face like the relaxed face, the
   baseline follows light and posture drift (τ ≈ 60 s), at most one log-odds unit per class
   away from the calibrated face: a slowly creeping expression is never absorbed.

Pure logic (NumPy only), clock passed in — unit-tested directly.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..vision.types import EMOTIONS, EmotionReading

NEUTRAL = EMOTIONS.index("neutral")
ANY = "*"  # an action word that fits every expression (head pose)

# p_ref: how neutral the relaxed face reads after calibration (higher = an expression must be
# clearer); the rest are the emotion engine's smoothing / switching rules
SENSITIVITY: dict[str, dict[str, float]] = {
    "calm": {"p_ref": 0.95, "min_prob": 0.50, "alpha": 0.15, "hold": 1.6, "margin": 0.15},
    "balanced": {"p_ref": 0.90, "min_prob": 0.42, "alpha": 0.20, "hold": 1.0, "margin": 0.12},
    "expressive": {"p_ref": 0.85, "min_prob": 0.32, "alpha": 0.30, "hold": 0.8, "margin": 0.08},
}

VA_REF = (0.0, -0.1)  # valence/arousal of a relaxed face
GAIN_MID, GAIN_WIDTH = 0.5, 0.5  # a class must gain ≳ half a logit on neutral to keep its share
POSE_PITCH_BONUS = 0.10  # neutral logit bonus per degree of pitch beyond 5° from the calibration pose
POSE_YAW_BONUS = 0.06  # … per degree of yaw beyond 8°
POSE_BONUS_MAX = 1.0  # bigger turns are handled by the frame weight: a clear expression never turns neutral
TALK_BONUS = 0.5  # a talking mouth is weak evidence of an expression
# slow adaptation: only frames the classifier reads like the relaxed face, and never far from it
ADAPT_MAX_INTENSITY = 0.3
ADAPT_MAX_DRIFT = 1.0  # log-odds per class from the calibrated relaxed face
ADAPT_MAX_BS_DRIFT = 0.25  # blendshape activation
ADAPT_MAX_POSE_DRIFT = 12.0  # degrees
ADAPT_MAX_VA_DRIFT = 0.3
LOGIT_LIMIT = 30.0
# hallmark facial actions: (floor, lo, hi) — the share multiplier rises from floor to 1 as the
# baseline-relative activation goes lo → hi. Anger has none: MediaPipe's brow blendshapes are
# not reliable enough to require (see the module docstring).
HALLMARK: dict[str, tuple[float, float, float]] = {
    "happiness": (0.35, 0.05, 0.25),
    "surprise": (0.35, 0.05, 0.25),
    "disgust": (0.35, 0.05, 0.25),
    "fear": (0.50, 0.05, 0.25),
    "sadness": (0.50, 0.03, 0.20),
    "contempt": (0.50, 0.03, 0.15),
}


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


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def neutral_margin(z: np.ndarray) -> float:
    """How much more "neutral" than "any expression" the classifier reads (log-odds)."""
    others = np.delete(z, NEUTRAL)
    top = others.max()
    return float(z[NEUTRAL] - (top + math.log(np.exp(others - top).sum())))


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


def hallmarks(bs: dict[str, float], base: dict[str, float]) -> dict[str, float]:
    """Baseline-relative activation of each expression's hallmark facial actions (FACS-style)."""
    x = _Delta(bs, base)
    return {
        "happiness": x.pmax("mouthSmile") + 0.5 * x.pair("cheekSquint"),
        "surprise": max(x.d("browInnerUp"), x.pair("browOuterUp"), x.pmax("eyeWide"), 0.7 * x.d("jawOpen")),
        "disgust": max(x.pmax("noseSneer"), x.pmax("mouthUpperUp")),
        "fear": max(x.d("browInnerUp"), x.pmax("eyeWide"), x.pmax("mouthStretch")),
        "sadness": max(x.pmax("mouthFrown"), x.d("browInnerUp"), 0.5 * x.d("mouthShrugLower")),
        "contempt": x.asym("mouthSmile") + 0.6 * x.asym("mouthDimple"),
    }


def hallmark_prior(bs: dict[str, float], base: dict[str, float]) -> np.ndarray:
    """Per-class share multiplier (1 = no objection; anger and neutral are never damped)."""
    h = hallmarks(bs, base)
    prior = np.ones(len(EMOTIONS))
    for name, (floor, lo, hi) in HALLMARK.items():
        prior[EMOTIONS.index(name)] = floor + (1.0 - floor) * smoothstep(lo, hi, h[name])
    return prior


# action words for the tutor, with the expressions they belong to (the note only names the ones
# that fit the expression it reports — a snarl stretches the lips, but it is not "smiling")
# words about the mouth are not said while the learner talks (speech moves the lips)
MOUTH_WORDS = frozenset({"smiling", "baring teeth", "upper lip raised", "lips pressed together",
                         "corners of the mouth turned down", "mouth open", "a one-sided smirk"})
ACTION_CLASSES: dict[str, tuple[str, ...]] = {
    "smiling": ("happiness", "contempt"),
    "baring teeth": ("anger", "disgust"),
    "upper lip raised": ("disgust", "anger"),
    "nose wrinkled": ("disgust", "anger"),
    "frowning, brows pulled down": ("anger", "sadness", "disgust", "fear"),
    "eyebrows raised": ("surprise", "fear", "sadness"),
    "eyes wide open": ("surprise", "fear"),
    "squinting": ("anger", "disgust", "happiness"),
    "lips pressed together": ("anger", "sadness", "disgust", "contempt"),
    "corners of the mouth turned down": ("sadness", "disgust", "anger", "contempt"),
    "mouth open": ("surprise", "fear"),
    "a one-sided smirk": ("contempt",),
    "looking down": (ANY,),
    "head tilted back": (ANY,),
    "looking away from the screen": (ANY,),
}


def actions_for(actions: tuple[str, ...] | list[str], expression: str | None) -> list[str]:
    """The action words that fit the reported expression (pose words always fit)."""
    out = []
    for a in actions:
        fits = ACTION_CLASSES.get(a, (ANY,))
        if ANY in fits or (expression is not None and expression in fits):
            out.append(a)
    return out


def facial_actions(bs: dict[str, float], base: dict[str, float], dpitch: float = 0.0, dyaw: float = 0.0,
                   speaking: bool = False) -> list[str]:
    """What is visibly different from the relaxed face, in plain words (for the tutor)."""
    x = _Delta(bs, base)
    out = []
    smiling = x.pmax("mouthSmile") >= 0.25
    if smiling:
        out.append("smiling")
    upper = x.pmax("mouthUpperUp")
    if upper >= 0.30 and (x.d("jawOpen") >= 0.10 or x.pmax("mouthLowerDown") >= 0.15):
        out.append("baring teeth")
    elif upper >= 0.30:
        out.append("upper lip raised")
    if x.pmax("noseSneer") >= 0.15:
        out.append("nose wrinkled")
    if x.pair("browDown") >= 0.20:
        out.append("frowning, brows pulled down")
    if max(x.d("browInnerUp"), x.pair("browOuterUp")) >= 0.20:
        out.append("eyebrows raised")
    if x.pmax("eyeWide") >= 0.20:
        out.append("eyes wide open")
    if x.pair("eyeSquint") >= 0.20 and not smiling:
        out.append("squinting")
    if max(x.pmax("mouthPress"), 0.6 * x.d("mouthShrugLower"), x.d("mouthRollLower")) >= 0.20:
        out.append("lips pressed together")
    if x.pmax("mouthFrown") >= 0.15:
        out.append("corners of the mouth turned down")
    if x.d("jawOpen") >= 0.35 and not speaking:
        out.append("mouth open")
    if x.asym("mouthSmile") >= 0.12 and not smiling:
        out.append("a one-sided smirk")
    if dpitch >= 15:
        out.append("looking down")
    elif dpitch <= -15:
        out.append("head tilted back")
    if abs(dyaw) >= 20:
        out.append("looking away from the screen")
    if speaking:
        out = [a for a in out if a not in MOUTH_WORDS]
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
    # the calibrated relaxed face (adaptation never drifts far from it)
    z0: np.ndarray | None = None
    bs0: dict[str, float] | None = None
    valence0: float | None = None
    arousal0: float | None = None
    pitch0: float | None = None
    yaw0: float | None = None

    def __post_init__(self) -> None:
        self.z0 = self.z.copy() if self.z0 is None else self.z0
        self.bs0 = dict(self.bs) if self.bs0 is None else self.bs0
        self.valence0 = self.valence if self.valence0 is None else self.valence0
        self.arousal0 = self.arousal if self.arousal0 is None else self.arousal0
        self.pitch0 = self.pitch if self.pitch0 is None else self.pitch0
        self.yaw0 = self.yaw if self.yaw0 is None else self.yaw0

    @property
    def margin(self) -> float:
        return neutral_margin(self.z)


@dataclass
class Corrected:
    probs: tuple[float, ...]
    valence: float | None
    arousal: float | None
    weight: float  # 0.1 … 1: how much this frame may move the smoothed estimate
    actions: tuple[str, ...]  # steady action words (filter with ``actions_for`` before naming them)
    margin: float  # neutral log-odds after calibration (diagnostics)


def pose_weight(dpitch: float, dyaw: float) -> float:
    """Full weight within ±6° pitch / ±8° yaw of the calibration pose, ~0.1 at 24° / 30°."""
    wp = 1.0 - max(0.0, abs(dpitch) - 6.0) / 18.0
    wy = 1.0 - max(0.0, abs(dyaw) - 8.0) / 22.0
    return max(0.1, min(1.0, wp)) * max(0.1, min(1.0, wy))


def pose_bonus(dpitch: float, dyaw: float) -> float:
    """Extra neutral log-odds for a head turned away from the calibration pose (capped: bigger
    turns only lower the frame's weight, so a clear expression is never pushed into neutral)."""
    bonus = POSE_PITCH_BONUS * max(0.0, abs(dpitch) - 5.0) + POSE_YAW_BONUS * max(0.0, abs(dyaw) - 8.0)
    return min(POSE_BONUS_MAX, bonus)


def _sigmoid(x: float) -> float:
    return 0.5 * (1.0 + math.tanh(x / 2.0))  # no overflow for any x


class Calibrator:
    """One per session. ``observe`` returns ``None`` while the baseline is being collected."""

    def __init__(self, seconds: float = 2.5, min_frames: int = 15, adapt_tau_s: float = 60.0,
                 sensitivity: str = "balanced") -> None:
        self.seconds = seconds
        self.min_frames = min_frames
        self.adapt_tau_s = adapt_tau_s
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
        finite = bool(np.isfinite(z).all())  # a broken frame must never poison the baseline
        z = np.nan_to_num(z, nan=0.0, posinf=LOGIT_LIMIT, neginf=-LOGIT_LIMIT)
        z = np.clip(z - z.mean(), -LOGIT_LIMIT, LOGIT_LIMIT)
        bs = bs or {}
        if pose:
            yaw, pitch = pose[0], pose[1]
        elif self.baseline is not None:  # no pose this frame: assume the calibration pose
            yaw, pitch = self.baseline.yaw, self.baseline.pitch
        else:
            yaw = pitch = 0.0
        dt = 0.0 if self._last_t is None else min(0.5, max(0.0, t - self._last_t))
        self._last_t = t
        if self.baseline is None:
            if finite:
                self._collect(z, reading, bs, pitch, yaw, dt, speaking)
            if self.baseline is None:
                return None  # still learning the relaxed face
        return self._correct(z, reading, bs, pitch, yaw, dt, speaking, finite)

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

    def rest_margin(self) -> float:
        """Neutral log-odds of the relaxed face after calibration: ``p_ref`` for a face that looks
        like an expression at rest; a very neutral face keeps half of its extra neutrality."""
        assert self.baseline is not None
        m_ref = logit(self.preset["p_ref"])
        return m_ref + 0.5 * max(0.0, self.baseline.margin - m_ref)

    def _correct(self, z: np.ndarray, r: EmotionReading, bs: dict[str, float], pitch: float, yaw: float,
                 dt: float, speaking: bool, finite: bool = True) -> Corrected:
        b = self.baseline
        assert b is not None
        dpitch, dyaw = pitch - b.pitch, yaw - b.yaw
        raw = _softmax(z)
        # how far each class has moved against neutral since the relaxed face (log-odds)
        gain = (z - z[NEUTRAL]) - (b.z - b.z[NEUTRAL])
        # 1) neutral vs. an expression. Intensity = the gains of what the face shows now, weighted
        #    by how much it shows it: a stern face that snarls (anger gains as neutral drops) and a
        #    stern face that smiles (happiness replaces anger — the neutral share hardly moves) both
        #    count; low-probability noise barely does.
        intensity = float(np.delete(raw * np.maximum(0.0, gain), NEUTRAL).sum())
        m = self.rest_margin() - intensity + pose_bonus(dpitch, dyaw) + (TALK_BONUS if speaking else 0.0)
        p_neutral = _sigmoid(m)
        # 2) which expression: the face as it looks now, among classes that gained on neutral
        #    since the relaxed face, softly checked against their hallmark facial actions
        prior = hallmark_prior(bs, b.bs) if bs else np.ones(len(EMOTIONS))
        share = raw * prior / (1.0 + np.exp(-(gain - GAIN_MID) / GAIN_WIDTH))
        share[NEUTRAL] = 0.0
        if share.sum() <= 1e-12:  # every class lost ground on neutral: share the rest as the face reads now
            share = raw * prior
            share[NEUTRAL] = 0.0
        if share.sum() > 0:
            share *= (1.0 - p_neutral) / share.sum()
            share[NEUTRAL] = p_neutral
        else:
            share[NEUTRAL] = 1.0
        # 3) valence/arousal: remove the relaxed face's bias in proportion to how relaxed the face is
        rest = float(share[NEUTRAL])
        v = a = None
        if r.valence is not None and math.isfinite(r.valence):
            v = float(np.clip(r.valence - rest * (b.valence - VA_REF[0]), -1.0, 1.0))
        if r.arousal is not None and math.isfinite(r.arousal):
            a = float(np.clip(r.arousal - rest * (b.arousal - VA_REF[1]), -1.0, 1.0))
        acts = tuple(facial_actions(bs, b.bs, dpitch, dyaw, speaking)) if bs else ()
        self._recent_actions.append(acts)
        weight = pose_weight(dpitch, dyaw) * (0.5 if speaking else 1.0)
        if finite:
            self._adapt(z, r, bs, pitch, yaw, dt, intensity, speaking)
        return Corrected(tuple(float(x) for x in share), v, a, max(0.1, weight), self.steady_actions(), m)

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
               intensity: float, speaking: bool) -> None:
        """Follow slow drift (light, posture) while the classifier reads the face like the relaxed
        face, never further than a bounded distance from the calibrated relaxed face (a slowly
        creeping expression must not be absorbed into "neutral")."""
        b = self.baseline
        if b is None or dt <= 0 or speaking or intensity >= ADAPT_MAX_INTENSITY:
            return
        if pose_weight(pitch - b.pitch, yaw - b.yaw) < 0.8:
            return
        assert b.z0 is not None and b.bs0 is not None
        eta = min(1.0, dt / self.adapt_tau_s)

        def toward(cur: float, new: float, anchor: float, limit: float) -> float:
            return float(np.clip(cur + eta * (new - cur), anchor - limit, anchor + limit))

        b.z = b.z0 + np.clip(b.z + eta * (z - b.z) - b.z0, -ADAPT_MAX_DRIFT, ADAPT_MAX_DRIFT)
        for k, val in bs.items():
            b.bs[k] = toward(b.bs.get(k, val), val, b.bs0.get(k, val), ADAPT_MAX_BS_DRIFT)
        b.pitch = toward(b.pitch, pitch, b.pitch0, ADAPT_MAX_POSE_DRIFT)
        b.yaw = toward(b.yaw, yaw, b.yaw0, ADAPT_MAX_POSE_DRIFT)
        if r.valence is not None and math.isfinite(r.valence):
            b.valence = toward(b.valence, r.valence, b.valence0, ADAPT_MAX_VA_DRIFT)
        if r.arousal is not None and math.isfinite(r.arousal):
            b.arousal = toward(b.arousal, r.arousal, b.arousal0, ADAPT_MAX_VA_DRIFT)
