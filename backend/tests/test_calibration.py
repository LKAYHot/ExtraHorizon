"""Per-person calibration: a biased resting face reads neutral, real expressions still show,
small brow shifts and a lowered head don't flip the estimate, talking is not an expression."""

from __future__ import annotations

import numpy as np
import pytest

from extrahorizon.emotion.calibration import SENSITIVITY, Calibrator, evidence, facial_actions, pose_weight
from extrahorizon.vision.types import EMOTIONS, EmotionReading

I = {k: i for i, k in enumerate(EMOTIONS)}
# a relaxed face that the raw classifier reads as "angry" (measured on a real user: anger 0.90–0.97)
RELAXED_BS = {"browDownLeft": 0.13, "browDownRight": 0.17, "eyeSquintLeft": 0.47, "eyeSquintRight": 0.40,
              "mouthSmileLeft": 0.0, "mouthSmileRight": 0.0, "jawOpen": 0.01, "mouthPressLeft": 0.02,
              "mouthPressRight": 0.02, "browInnerUp": 0.0, "eyeWideLeft": 0.0, "eyeWideRight": 0.0}


def reading(shift: dict[str, float] | None = None, base_anger: float = 4.5, v: float = -0.5, a: float = 0.9) -> EmotionReading:
    z = np.zeros(len(EMOTIONS))
    z[I["anger"]] = base_anger  # the classifier's bias for this face
    z[I["neutral"]] = 0.1
    for k, dz in (shift or {}).items():
        z[I[k]] += dz
    p = np.exp(z - z.max())
    p /= p.sum()
    return EmotionReading(probs=tuple(p), valence=v, arousal=a, logits=tuple(z))


def bs(**changes: float) -> dict[str, float]:
    out = dict(RELAXED_BS)
    out.update(changes)
    return out


def calibrated(level: str = "balanced", pitch: float = 0.0) -> tuple[Calibrator, float]:
    c = Calibrator(sensitivity=level)
    t = 0.0
    while not c.ready:
        assert c.observe(t, reading(), RELAXED_BS, (0.0, pitch, 0.0)) is None or c.ready
        t += 0.1
        assert t < 5
    return c, t


def top(probs) -> str:
    return EMOTIONS[int(np.argmax(probs))]


def test_learning_the_relaxed_face_takes_about_two_and_a_half_seconds():
    c = Calibrator()
    t = 0.0
    while not c.ready:
        c.observe(t, reading(), RELAXED_BS, (0.0, 0.0, 0.0))
        t += 0.1
    assert 2.4 <= t <= 2.8 and c.public() == {"state": "ready", "progress": 1.0, "sensitivity": "balanced"}


def test_the_biased_resting_face_reads_neutral_after_calibration():
    raw = reading()
    assert top(raw.probs) == "anger" and raw.probs[I["anger"]] > 0.9  # what the model says without calibration
    c, t = calibrated()
    out = c.observe(t, raw, RELAXED_BS, (0.0, 0.0, 0.0))
    assert top(out.probs) == "neutral" and out.probs[I["neutral"]] > 0.6
    assert abs(out.valence) < 0.1 and out.weight == 1.0 and out.actions == ()


def test_a_real_expression_still_shows():
    c, t = calibrated()
    smile = c.observe(t, reading({"happiness": 6.0}, v=0.6), bs(mouthSmileLeft=0.7, mouthSmileRight=0.65), (0, 0, 0))
    assert top(smile.probs) == "happiness" and smile.probs[I["happiness"]] > 0.6 and "smiling" in smile.actions
    for k in range(6):  # held for about half a second (single-frame flickers are not reported)
        angry = c.observe(t + 0.1 * (k + 1), reading({"anger": 3.5}), bs(browDownLeft=0.6, browDownRight=0.62,
                                                                          mouthPressLeft=0.4), (0, 0, 0))
    assert top(angry.probs) == "anger" and "frowning, brows pulled down" in angry.actions


def test_a_small_brow_shift_stays_neutral():
    c, t = calibrated()
    out = c.observe(t, reading({"anger": 1.0}), bs(browDownLeft=0.2, browDownRight=0.23), (0, 0, 0))
    assert top(out.probs) == "neutral"


def test_the_classifier_alone_cannot_make_an_expression_without_facial_evidence():
    c, t = calibrated()
    out = c.observe(t, reading({"contempt": 4.0}), RELAXED_BS, (0, 0, 0))  # nothing moved on the face
    assert top(out.probs) == "neutral"
    with_evidence = c.observe(t + 0.1, reading({"contempt": 4.0}), bs(mouthSmileLeft=0.35), (0, 0, 0))  # one-sided smile
    assert with_evidence.probs[I["contempt"]] > out.probs[I["contempt"]] * 2


def test_a_lowered_head_counts_less_and_needs_more_evidence():
    c, t = calibrated()
    down = c.observe(t, reading({"anger": 2.0}), RELAXED_BS, (0.0, 14.0, 0.0))  # head tilted down by 14°
    assert down.weight < 0.7 and top(down.probs) == "neutral" and "looking down" not in down.actions
    far = c.observe(t + 0.1, reading(), RELAXED_BS, (0.0, 26.0, 0.0))
    assert far.weight == pytest.approx(0.1)
    assert pose_weight(0, 0) == 1.0 and pose_weight(6, 8) == 1.0 and pose_weight(15, 0) == pytest.approx(0.5)


def test_talking_is_not_an_expression():
    c = Calibrator()
    t = 0.0
    for _ in range(40):  # 4 s of talking: nothing is learned from a moving mouth …
        c.observe(t, reading(), bs(jawOpen=0.5), (0, 0, 0), speaking=True)
        t += 0.1
    assert not c.ready and c.progress == 0.0
    while not c.ready:  # … unless the face never settles (then it is taken as it is)
        c.observe(t, reading(), bs(jawOpen=0.5), (0, 0, 0), speaking=True)
        t += 0.1
        assert t < 20
    out = c.observe(t, reading(), RELAXED_BS, (0, 0, 0), speaking=True)
    assert out.weight == pytest.approx(0.5)  # while the learner talks frames count half


def test_the_baseline_follows_slow_drift_but_not_expressions():
    c, t = calibrated()
    before = c.baseline.z.copy()
    for _ in range(300):  # 30 s of a relaxed face in slightly different light
        c.observe(t, reading({"sadness": 0.8}), RELAXED_BS, (0, 0, 0))
        t += 0.1
    moved = np.abs(c.baseline.z - before).max()
    assert 0.05 < moved < 0.8
    frozen = c.baseline.z.copy()
    for _ in range(100):  # a long smile is not absorbed into "neutral"
        c.observe(t, reading({"happiness": 6.0}), bs(mouthSmileLeft=0.7, mouthSmileRight=0.7), (0, 0, 0))
        t += 0.1
    assert np.allclose(c.baseline.z, frozen)


def test_sensitivity_changes_how_much_evidence_is_needed():
    probs = {}
    for level in ("calm", "balanced", "expressive"):
        c, t = calibrated(level)
        out = c.observe(t, reading({"surprise": 4.0}), bs(browInnerUp=0.12, eyeWideLeft=0.08), (0, 0, 0))
        probs[level] = out.probs[I["surprise"]]
    assert probs["calm"] < probs["balanced"] < probs["expressive"]
    assert set(SENSITIVITY) == {"calm", "balanced", "expressive"}


def test_restart_and_sensitivity_switch():
    c, _ = calibrated()
    c.set_sensitivity("calm")
    c.restart()
    assert not c.ready and c.public() == {"state": "collecting", "progress": 0.0, "sensitivity": "calm"}
    c.set_sensitivity("nonsense")
    assert c.level == "calm"


def test_evidence_and_actions_are_baseline_relative():
    base = dict(RELAXED_BS)
    assert all(v == 0 for v in evidence(base, base).values())  # the resting face itself is no evidence
    ev = evidence(bs(browDownLeft=0.55, browDownRight=0.57), base)
    assert ev["anger"] > 0.4 and ev["happiness"] == 0
    assert facial_actions(bs(browInnerUp=0.3), base) == ["eyebrows raised"]
    assert "looking away from the screen" in facial_actions(base, base, dyaw=25)
