"""Plain data types of the vision pipeline — no numpy / OpenCV / MediaPipe imports here,
so the chat side of the backend keeps working even if those native libraries are broken."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    proc_ms: float = 0.0
