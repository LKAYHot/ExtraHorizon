"""Frame quality gates: anything unreliable becomes ``unknown`` with a reason.

Unknown is never mapped to "neutral": no face, several faces (ambiguous — we never
read a random person's face), a face too small / turned away / badly lit, or an
undecodable frame all mean "no estimate right now".
"""

from __future__ import annotations

from typing import Any

from .types import FrameResult

OK = "ok"
UNKNOWN = "unknown"


def assess_quality(frame: FrameResult, s: Any) -> tuple[str, str | None]:
    if not frame.ok:
        return UNKNOWN, frame.error or "bad_frame"
    if frame.faces == 0:
        return UNKNOWN, "no_face"
    if frame.faces > 1:
        return UNKNOWN, "multiple_faces"
    if frame.blendshapes is None and frame.emotion is None:
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
    if frame.emotion is None:
        return UNKNOWN, "no_emotion_estimate"
    return OK, None
