"""Vision: quality gates → unknown, and the real on-device models on a real portrait."""

from __future__ import annotations

import pytest

from extrahorizon.vision.quality import OK, UNKNOWN, assess_quality
from extrahorizon.vision.types import EMOTIONS, EmotionReading, FrameResult

from .conftest import make_settings

S = make_settings()
READING = EmotionReading(probs=tuple([0.6] + [0.4 / 7] * 7), valence=0.1, arousal=0.0)


def face(**kw) -> FrameResult:
    base = dict(ok=True, faces=1, boxes=[[0.3, 0.2, 0.3, 0.4]], blendshapes={"browDownLeft": 0.1}, pose=(0.0, 5.0, 0.0),
                brightness=120.0, face_width=0.3, emotion=READING)
    base.update(kw)
    return FrameResult(**base)


@pytest.mark.parametrize(
    "frame,reason",
    [
        (FrameResult(ok=False, error="bad_frame"), "bad_frame"),
        (face(faces=0, blendshapes=None, boxes=[], emotion=None), "no_face"),
        (face(faces=2, blendshapes=None, emotion=None), "multiple_faces"),
        (face(face_width=0.05), "face_too_small"),
        (face(pose=(45.0, 0.0, 0.0)), "head_turned"),
        (face(pose=(0.0, -40.0, 0.0)), "head_turned"),
        (face(brightness=12.0), "too_dark"),
        (face(brightness=250.0), "overexposed"),
        (face(emotion=None), "no_emotion_estimate"),
    ],
)
def test_unreliable_frames_are_unknown(frame, reason):
    assert assess_quality(frame, S) == (UNKNOWN, reason)


def test_good_frame_passes_the_gates():
    assert assess_quality(face(), S) == (OK, None)


def test_emotion_classifier_on_a_real_portrait(emotion_model_path, portrait_jpeg):
    import cv2
    import numpy as np

    from extrahorizon.emotion.classifier import EmotionClassifier

    clf = EmotionClassifier(emotion_model_path)
    img = cv2.imdecode(np.frombuffer(portrait_jpeg, np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    crop = clf.crop(img, [0.3, 0.15, 0.4, 0.5])
    assert crop is not None and crop.shape[2] == 3
    r = clf.predict(crop)
    assert len(r.probs) == len(EMOTIONS) and abs(sum(r.probs) - 1) < 1e-6
    assert -1 <= r.valence <= 1 and -1 <= r.arousal <= 1
    assert r.ms < 500
    assert clf.crop(img, [0.0, 0.0, 0.001, 0.001]) is None  # too small to classify


def test_real_mediapipe_and_emotion_on_a_portrait(model_path, emotion_model_path, portrait_jpeg):
    import cv2
    import numpy as np

    from extrahorizon.emotion.classifier import EmotionClassifier
    from extrahorizon.vision.analyzer import FaceAnalyzer

    a = FaceAnalyzer(model_path, emotion=EmotionClassifier(emotion_model_path))
    try:
        img = cv2.imdecode(np.frombuffer(portrait_jpeg, np.uint8), cv2.IMREAD_COLOR)
        small = cv2.resize(img, (480, int(img.shape[0] * 480 / img.shape[1])))
        r = a.analyze_jpeg(cv2.imencode(".jpg", small)[1].tobytes())
        assert r.ok and r.faces == 1 and r.emotion is not None
        assert abs(sum(r.emotion.probs) - 1) < 1e-6
        yaw, pitch, roll = r.pose
        assert abs(yaw) < 15 and abs(pitch) < 15 and abs(roll) < 10  # a frontal portrait
        assert assess_quality(r, S) == (OK, None)
        two = np.hstack([small, cv2.flip(small, 1)])
        r2 = a.analyze_bgr(two)
        assert r2.faces == 2 and r2.emotion is None  # never read one of several faces
        assert assess_quality(r2, S) == (UNKNOWN, "multiple_faces")
        dark = (small * 0.1).astype(np.uint8)
        assert assess_quality(a.analyze_bgr(dark), S)[0] == UNKNOWN
        assert a.analyze_jpeg(b"definitely not a jpeg").error == "bad_frame"
    finally:
        a.close()
