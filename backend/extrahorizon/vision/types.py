"""Plain data types of the vision pipeline — no numpy / OpenCV / MediaPipe / ONNX imports,
so the chat side of the backend keeps working even if those native libraries are broken."""

from __future__ import annotations

from dataclasses import dataclass, field

# Output order of the EmotiEffLib 8-class models (AffectNet classes)
EMOTIONS: tuple[str, ...] = (
    "anger",
    "contempt",
    "disgust",
    "fear",
    "happiness",
    "neutral",
    "sadness",
    "surprise",
)


@dataclass
class EmotionReading:
    """One frame's facial-expression estimate for exactly one face."""

    probs: tuple[float, ...]  # softmax over EMOTIONS
    valence: float | None = None  # ≈ -1 (negative) … +1 (positive)
    arousal: float | None = None  # ≈ -1 (calm) … +1 (excited)
    ms: float = 0.0
    logits: tuple[float, ...] | None = None  # raw class scores (for per-person calibration)


@dataclass
class FrameResult:
    ok: bool  # frame decoded and analysed
    error: str | None = None  # bad_frame | analysis_failed
    faces: int = 0
    boxes: list[list[float]] = field(default_factory=list)  # normalised [x, y, w, h]
    blendshapes: dict[str, float] | None = None  # only when exactly one face
    pose: tuple[float, float, float] | None = None  # yaw, pitch, roll (degrees)
    brightness: float | None = None  # mean luma inside the face box (0..255)
    face_width: float | None = None  # face box width / frame width
    emotion: EmotionReading | None = None  # only when exactly one face
    proc_ms: float = 0.0
