"""Vision: quality gates → unknown, calibration, and the confusion proxy's behaviour."""

from __future__ import annotations

import pytest

from extrahorizon.engine import CALIBRATING, OK, UNKNOWN
from extrahorizon.vision.types import FrameResult
from extrahorizon.vision.proxy import ConfusionProxy, ProxyParams, assess_quality, extract_features

from .conftest import make_settings

S = make_settings()
NEUTRAL = {"browDownLeft": 0.05, "browDownRight": 0.06, "eyeSquintLeft": 0.10, "eyeSquintRight": 0.12,
           "mouthPressLeft": 0.05, "mouthPressRight": 0.05, "mouthSmileLeft": 0.02, "mouthSmileRight": 0.02,
           "browInnerUp": 0.1, "eyeBlinkLeft": 0.05, "eyeBlinkRight": 0.05}


def face(**kw) -> FrameResult:
    base = dict(ok=True, faces=1, boxes=[[0.3, 0.2, 0.3, 0.4]], blendshapes=dict(NEUTRAL), pose=(0.0, 5.0, 0.0),
                brightness=120.0, face_width=0.3)
    base.update(kw)
    return FrameResult(**base)


def calibrated(neutral=NEUTRAL) -> ConfusionProxy:
    p = ConfusionProxy(ProxyParams())
    t = 0.0
    while p.baseline is None:
        p.update(t, extract_features(neutral))
        t += 0.1
    return p


@pytest.mark.parametrize(
    "frame,reason",
    [
        (FrameResult(ok=False, error="bad_frame"), "bad_frame"),
        (face(faces=0, blendshapes=None, boxes=[]), "no_face"),
        (face(faces=2, blendshapes=None), "multiple_faces"),
        (face(face_width=0.05), "face_too_small"),
        (face(pose=(45.0, 0.0, 0.0)), "head_turned"),
        (face(pose=(0.0, -40.0, 0.0)), "head_turned"),
        (face(brightness=12.0), "too_dark"),
        (face(brightness=250.0), "overexposed"),
    ],
)
def test_unreliable_frames_are_unknown(frame, reason):
    assert assess_quality(frame, S) == (UNKNOWN, reason)


def test_good_frame_passes_the_gates():
    assert assess_quality(face(), S) == (OK, None)


def test_calibration_takes_time_not_frames():
    feats = extract_features(NEUTRAL)
    p = ConfusionProxy(ProxyParams(calibration_s=2.5, calibration_min_samples=10))
    for i in range(50):  # 50 frames within 0.5 s: many frames, too little time
        r = p.update(i * 0.01, feats)
    assert r.status == CALIBRATING and p.baseline is None and 0 < r.progress < 1
    t = 0.5
    while t < 2.45:
        r = p.update(t, feats)
        t += 0.1
    assert r.status == CALIBRATING
    r = p.update(2.55, feats)
    assert r.status == OK and p.baseline is not None


def test_a_long_break_restarts_calibration():
    feats = extract_features(NEUTRAL)
    p = ConfusionProxy(ProxyParams(calibration_s=2.5))
    for i in range(20):  # 2 s of calibration …
        p.update(i * 0.1, feats)
    r = p.update(4.0, feats)  # … then a 2 s break (someone else may be in front of the camera)
    assert r.status == CALIBRATING and r.progress == 0


def test_neutral_face_reads_low():
    p = calibrated()
    assert p.update(10.0, extract_features(NEUTRAL)).value < 0.1


def test_brow_lowering_and_lid_tightening_read_high():
    p = calibrated()
    frown = dict(NEUTRAL, browDownLeft=0.55, browDownRight=0.57, eyeSquintLeft=0.45, eyeSquintRight=0.47)
    assert p.update(10.0, extract_features(frown)).value > 0.65


def test_brow_lowering_alone_can_cross_the_threshold():
    p = calibrated()
    frown = dict(NEUTRAL, browDownLeft=0.45, browDownRight=0.45)
    assert p.update(10.0, extract_features(frown)).value > 0.65


def test_smiling_suppresses_the_proxy():
    p = calibrated()
    frown_smile = dict(NEUTRAL, browDownLeft=0.55, browDownRight=0.57, eyeSquintLeft=0.45, eyeSquintRight=0.47,
                       mouthSmileLeft=0.8, mouthSmileRight=0.8)
    assert p.update(10.0, extract_features(frown_smile)).value < 0.1


def test_blinking_does_not_fake_a_squint():
    p = calibrated()
    blink = dict(NEUTRAL, eyeSquintLeft=0.6, eyeSquintRight=0.6, eyeBlinkLeft=0.95, eyeBlinkRight=0.95)
    assert p.update(10.0, extract_features(blink)).value < 0.1


def test_baseline_is_personal():
    """A person whose resting brow already reads high is not 'confused' by default."""
    resting_high = dict(NEUTRAL, browDownLeft=0.7, browDownRight=0.72)
    p = calibrated(resting_high)
    assert p.update(10.0, extract_features(resting_high)).value < 0.1
    frown = dict(resting_high, browDownLeft=0.95, browDownRight=0.96)  # little headroom left
    assert p.update(10.1, extract_features(frown)).value > 0.65


def test_long_absence_triggers_recalibration():
    p = calibrated()
    p.note_absence(100.0)  # 90+ s without a usable face (new person at the laptop?)
    assert p.baseline is None
    assert p.update(100.1, extract_features(NEUTRAL)).status == CALIBRATING


def test_real_mediapipe_on_a_portrait(model_path, portrait_jpeg):
    import cv2
    import numpy as np

    from extrahorizon.vision.analyzer import FaceAnalyzer

    a = FaceAnalyzer(model_path)
    try:
        img = cv2.imdecode(np.frombuffer(portrait_jpeg, np.uint8), cv2.IMREAD_COLOR)
        small = cv2.resize(img, (480, int(img.shape[0] * 480 / img.shape[1])))
        r = a.analyze_jpeg(cv2.imencode(".jpg", small)[1].tobytes())
        assert r.ok and r.faces == 1 and len(r.blendshapes) == 52
        yaw, pitch, roll = r.pose
        assert abs(yaw) < 15 and abs(pitch) < 15 and abs(roll) < 10  # a frontal portrait
        assert assess_quality(r, S) == (OK, None)
        rotated = cv2.warpAffine(small, cv2.getRotationMatrix2D((240, small.shape[0] / 2), 20, 1.0),
                                 (480, small.shape[0]))
        assert 15 < a.analyze_bgr(rotated).pose[2] < 27  # roll follows the in-plane rotation
        dark = (small * 0.1).astype(np.uint8)
        assert assess_quality(a.analyze_bgr(dark), S) == (UNKNOWN, "too_dark")
        assert a.analyze_jpeg(b"definitely not a jpeg").error == "bad_frame"
    finally:
        a.close()
