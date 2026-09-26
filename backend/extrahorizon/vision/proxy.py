"""Confusion *proxy* — an explicitly heuristic estimate, not an emotion classifier.

MediaPipe Face Landmarker returns 52 ARKit-style blendshape coefficients; it does
not classify "confusion". We map a few coefficients that learning-affect research
has associated with confusion (brow lowering ≈ AU4, lid tightening ≈ AU7, lip
pressing ≈ AU24) into one number in [0, 1]:

1. per-session neutral **baseline** (median over the first ``calibration_s`` of
   good frames) — resting faces differ a lot between people;
2. baseline-corrected, headroom-aware deviations ``d ∈ [0, 1]``;
3. noisy-OR combination ``1 − Π(1 − w·d)`` (brow lowering dominates);
4. multiplied by a smile suppression factor (smiling co-activates the same
   coefficients but is not confusion).

The same expressions also occur with concentration, squinting at a bright
screen, frustration, etc. The UI therefore labels it "confusion proxy (estimate)"
and the LLM never sees the number. See docs/CONFUSION_PROXY.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any

from ..engine import CALIBRATING, OK, UNKNOWN
from .types import FrameResult

FEATURES = ("brow_lower", "lid_tighten", "lip_press", "smile", "brow_raise_inner", "blink")


def extract_features(bs: dict[str, float]) -> dict[str, float]:
    g = bs.get
    return {
        "brow_lower": (g("browDownLeft", 0.0) + g("browDownRight", 0.0)) / 2,
        "lid_tighten": (g("eyeSquintLeft", 0.0) + g("eyeSquintRight", 0.0)) / 2,
        "lip_press": (g("mouthPressLeft", 0.0) + g("mouthPressRight", 0.0)) / 2,
        "smile": (g("mouthSmileLeft", 0.0) + g("mouthSmileRight", 0.0)) / 2,
        "brow_raise_inner": g("browInnerUp", 0.0),
        "blink": (g("eyeBlinkLeft", 0.0) + g("eyeBlinkRight", 0.0)) / 2,
    }


def assess_quality(frame: FrameResult, s: Any) -> tuple[str, str | None]:
    """Gate a frame: anything unreliable becomes ``unknown`` with a reason."""
    if not frame.ok:
        return UNKNOWN, frame.error or "bad_frame"
    if frame.faces == 0:
        return UNKNOWN, "no_face"
    if frame.faces > 1:
        return UNKNOWN, "multiple_faces"  # ambiguous: never adapt to a random face
    if frame.blendshapes is None:
        return UNKNOWN, "no_face"
    if frame.face_width is not None and frame.face_width < s.min_face_width:
        return UNKNOWN, "face_too_small"
    if frame.pose is not None:
        yaw, pitch, _ = frame.pose
        if abs(yaw) > s.max_abs_yaw_deg or abs(pitch) > s.max_abs_pitch_deg:
            return UNKNOWN, "head_turned"
    if frame.brightness is not None:
        if frame.brightness < s.min_brightness:
            return UNKNOWN, "too_dark"
        if frame.brightness > s.max_brightness:
            return UNKNOWN, "overexposed"
    return OK, None


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


@dataclass(frozen=True)
class ProxyParams:
    w_brow: float = 0.85
    w_lid: float = 0.45
    w_press: float = 0.30
    scale_brow: float = 0.30
    scale_lid: float = 0.30
    scale_press: float = 0.30
    min_scale: float = 0.12
    smile_start: float = 0.15
    smile_full: float = 0.45
    calibration_s: float = 2.5
    calibration_min_samples: int = 10
    calibration_max_gap_s: float = 1.5  # a longer break restarts calibration
    recalibrate_after_absence_s: float = 45.0  # new person / new seat → new baseline

    @classmethod
    def from_settings(cls, s: Any) -> "ProxyParams":
        return cls(
            w_brow=s.proxy_w_brow,
            w_lid=s.proxy_w_lid,
            w_press=s.proxy_w_press,
            scale_brow=s.proxy_scale_brow,
            scale_lid=s.proxy_scale_lid,
            scale_press=s.proxy_scale_press,
            min_scale=s.proxy_min_scale,
            smile_start=s.proxy_smile_start,
            smile_full=s.proxy_smile_full,
            calibration_s=s.calibration_s,
            calibration_min_samples=s.calibration_min_samples,
        )


@dataclass
class ProxyReading:
    status: str  # ok | calibrating
    value: float | None
    progress: float = 1.0  # calibration progress 0..1
    contrib: dict[str, float] = field(default_factory=dict)


class ConfusionProxy:
    """Per-session calibration baseline + proxy computation."""

    def __init__(self, params: ProxyParams) -> None:
        self.params = params
        self.reset()

    def reset(self) -> None:
        self.baseline: dict[str, float] | None = None
        self._calib: list[dict[str, float]] = []
        self._calib_t0: float | None = None
        self._calib_last: float | None = None
        self._last_valid_t: float | None = None

    def note_absence(self, t: float) -> None:
        """Called for frames without a usable face; long absence → recalibrate."""
        if (
            self.baseline is not None
            and self._last_valid_t is not None
            and t - self._last_valid_t > self.params.recalibrate_after_absence_s
        ):
            self.reset()

    def update(self, t: float, feats: dict[str, float]) -> ProxyReading:
        p = self.params
        self.note_absence(t)
        self._last_valid_t = t
        if self.baseline is None:
            if self._calib_last is not None and t - self._calib_last > p.calibration_max_gap_s:
                self._calib, self._calib_t0 = [], None
            if self._calib_t0 is None:
                self._calib_t0 = t
            self._calib.append(feats)
            self._calib_last = t
            span = t - self._calib_t0
            if span >= p.calibration_s and len(self._calib) >= p.calibration_min_samples:
                self.baseline = {k: median(f[k] for f in self._calib) for k in FEATURES}
                self._calib = []
            else:
                return ProxyReading(status=CALIBRATING, value=None, progress=_clamp(span / p.calibration_s))
        value, contrib = self.compute(feats)
        return ProxyReading(status=OK, value=value, contrib=contrib)

    def compute(self, feats: dict[str, float]) -> tuple[float, dict[str, float]]:
        p = self.params
        b = self.baseline or {k: 0.0 for k in FEATURES}

        def dev(name: str, scale: float) -> float:
            base = b[name]
            eff = max(p.min_scale, min(scale, (1.0 - base) * 0.9))  # headroom-aware
            return _clamp((feats[name] - base) / eff)

        d_brow = dev("brow_lower", p.scale_brow)
        d_lid = dev("lid_tighten", p.scale_lid)
        d_press = dev("lip_press", p.scale_press)
        blink_gate = _clamp((feats["blink"] - 0.45) / 0.3)  # closing eyes fake a squint
        e_brow = p.w_brow * d_brow
        e_lid = p.w_lid * d_lid * (1.0 - blink_gate)
        e_press = p.w_press * d_press
        raw = 1.0 - (1.0 - e_brow) * (1.0 - e_lid) * (1.0 - e_press)
        d_smile = feats["smile"] - b["smile"]
        span = max(1e-6, p.smile_full - p.smile_start)
        suppression = 1.0 - _clamp((d_smile - p.smile_start) / span)
        value = _clamp(raw * suppression)
        return value, {
            "brow_lower": round(e_brow, 3),
            "lid_tighten": round(e_lid, 3),
            "lip_press": round(e_press, 3),
            "smile_factor": round(suppression, 3),
        }
