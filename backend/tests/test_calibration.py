"""Per-person calibration: a biased resting face reads neutral, real expressions still show — with
the class the face actually looks like — small shifts, a lowered head and talking don't flip it.

The "stern" face below is modelled on measurements of a real learner (laptop webcam, heavy
brows): the classifier read the relaxed face as anger 0.96; a snarl as anger 0.98 with neutral
far lower; lips pressed together as anger 0.55 / disgust 0.44."""

from __future__ import annotations

import numpy as np
import pytest

from extrahorizon.emotion.calibration import (
    SENSITIVITY,
    Calibrator,
    actions_for,
    facial_actions,
    hallmark_prior,
    hallmarks,
    neutral_margin,
    pose_weight,
)
from extrahorizon.vision.types import EMOTIONS, EmotionReading

I = {k: i for i, k in enumerate(EMOTIONS)}
# measured centred logits (ang, con, dis, fea, hap, neu, sad, sur) of the real learner's frames
STERN_REST = [5.8, -0.6, 0.3, -1.6, -4.8, 1.1, 1.9, -2.1]
SNARL = [6.5, -2.1, 2.3, 1.3, -3.4, -1.9, -0.8, -1.9]
PRESSED = [5.4, -0.6, 5.2, -0.9, -3.0, -1.8, -2.4, -1.9]
# a relaxed face that the raw classifier reads as "angry" (brows low, squinting at a screen)
RELAXED_BS = {"browDownLeft": 0.34, "browDownRight": 0.48, "eyeSquintLeft": 0.55, "eyeSquintRight": 0.53,
              "mouthSmileLeft": 0.0, "mouthSmileRight": 0.0, "jawOpen": 0.01, "mouthPressLeft": 0.02,
              "mouthPressRight": 0.02, "browInnerUp": 0.0, "eyeWideLeft": 0.0, "eyeWideRight": 0.0,
              "mouthPucker": 0.88}
SNARL_BS = {**RELAXED_BS, "browDownLeft": 0.0, "browDownRight": 0.06, "eyeSquintLeft": 0.65, "mouthUpperUpLeft": 0.56,
            "mouthUpperUpRight": 0.50, "mouthLowerDownLeft": 0.36, "mouthLowerDownRight": 0.42,
            "mouthSmileLeft": 0.37, "mouthSmileRight": 0.37, "jawOpen": 0.46, "mouthPucker": 0.0}
PRESSED_BS = {**RELAXED_BS, "browDownLeft": 0.19, "browDownRight": 0.33, "mouthShrugLower": 0.75,
              "mouthDimpleLeft": 0.74, "mouthDimpleRight": 0.83, "mouthPucker": 0.0}


def reading(z: list[float] | None = None, shift: dict[str, float] | None = None, v: float = -0.67,
            a: float = 0.89) -> EmotionReading:
    z = np.array(STERN_REST if z is None else z, dtype=float)
    for k, dz in (shift or {}).items():
        z[I[k]] += dz
    p = np.exp(z - z.max())
    p /= p.sum()
    return EmotionReading(probs=tuple(p), valence=v, arousal=a, logits=tuple(z))


def bs(**changes: float) -> dict[str, float]:
    out = dict(RELAXED_BS)
    out.update(changes)
    return out


def calibrated(level: str = "balanced", rest: list[float] | None = None, rest_bs: dict | None = None,
               pitch: float = 0.0) -> tuple[Calibrator, float]:
    c = Calibrator(sensitivity=level)
    t = 0.0
    while not c.ready:
        out = c.observe(t, reading(rest), rest_bs or RELAXED_BS, (0.0, pitch, 0.0))
        assert out is None or c.ready  # the frame completing the baseline is already corrected
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
    assert top(out.probs) == "neutral" and out.probs[I["neutral"]] == pytest.approx(0.9, abs=0.02)
    assert abs(out.valence) < 0.1 and out.weight == 1.0 and out.actions == ()


def test_a_stern_face_that_snarls_reads_angry_not_disgusted():
    c, t = calibrated()
    for k in range(6):  # held for about half a second (single-frame flickers are not reported)
        out = c.observe(t + 0.1 * k, reading(SNARL, v=-0.64, a=1.0), SNARL_BS, (0, 0, 0))
    assert top(out.probs) == "anger" and out.probs[I["anger"]] > 0.8
    assert out.probs[I["disgust"]] < 0.1 and out.valence < -0.5 and out.arousal > 0.8
    assert "baring teeth" in out.actions
    assert actions_for(out.actions, "anger") == ["baring teeth"]  # the stretched lips are not "smiling"


def test_lips_pressed_together_read_angry_disgust_needs_a_raised_lip_or_wrinkled_nose():
    c, t = calibrated()
    for k in range(6):
        out = c.observe(t + 0.1 * k, reading(PRESSED, v=-0.7, a=1.0), PRESSED_BS, (0, 0, 0))
    assert top(out.probs) == "anger" and out.probs[I["anger"]] > 2 * out.probs[I["disgust"]]
    assert "lips pressed together" in out.actions
    # with the hallmark of disgust (upper lip raised) the same classifier reading leans to disgust
    c2, t2 = calibrated()
    lifted = c2.observe(t2, reading(PRESSED), {**PRESSED_BS, "mouthUpperUpLeft": 0.4}, (0, 0, 0))
    assert lifted.probs[I["disgust"]] > out.probs[I["disgust"]] * 2


def test_a_stern_face_that_smiles_is_happy_not_angry():
    c, t = calibrated()
    smile = reading(shift={"happiness": 10.5, "anger": -4.8, "neutral": -0.6}, v=0.6, a=0.4)
    out = c.observe(t, smile, bs(mouthSmileLeft=0.7, mouthSmileRight=0.65, cheekSquintLeft=0.3), (0, 0, 0))
    assert top(out.probs) == "happiness" and out.probs[I["anger"]] < 0.05 and out.valence > 0.3


def test_a_small_shift_stays_neutral():
    c, t = calibrated()
    for shift in ({"anger": 1.0}, {"contempt": 2.0}, {"neutral": -1.0}):
        out = c.observe(t, reading(shift=shift), bs(browDownLeft=0.4, browDownRight=0.55), (0, 0, 0))
        assert top(out.probs) == "neutral", shift
        t += 0.1


def test_a_neutral_resting_face_keeps_the_classifier_s_own_judgement():
    rest = [0.0, 0.0, 0.0, 0.0, 0.0, 4.5, 0.0, 0.0]  # reads neutral ≈ 0.94 without calibration
    c, t = calibrated(rest=rest, rest_bs={})
    relaxed = c.observe(t, reading(rest), {}, (0, 0, 0))
    assert relaxed.probs[I["neutral"]] > 0.9
    angry = c.observe(t + 0.1, reading(rest, {"anger": 6.0, "neutral": -3.0}), {}, (0, 0, 0))
    assert top(angry.probs) == "anger" and angry.probs[I["anger"]] > 0.8


def test_the_classifier_alone_can_show_an_expression_but_hallmarks_steer_which_one():
    c, t = calibrated()
    # nothing measurable moved on the face (MediaPipe misses many brow movements) — anger still shows
    out = c.observe(t, reading(SNARL), RELAXED_BS, (0, 0, 0))
    assert top(out.probs) == "anger"
    prior = hallmark_prior(RELAXED_BS, RELAXED_BS)
    assert prior[I["anger"]] == 1.0 and prior[I["neutral"]] == 1.0 and prior[I["disgust"]] < 0.5
    assert hallmark_prior(bs(mouthSmileLeft=0.4), RELAXED_BS)[I["happiness"]] == 1.0


def test_a_lowered_head_counts_less_and_needs_a_clearer_expression():
    c, t = calibrated()
    down = c.observe(t, reading(shift={"neutral": -1.8}), RELAXED_BS, (0.0, 14.0, 0.0))  # head tilted down by 14°
    level = c.observe(t + 0.1, reading(shift={"neutral": -1.8}), RELAXED_BS, (0.0, 0.0, 0.0))
    assert down.weight < 0.7 and down.probs[I["neutral"]] > level.probs[I["neutral"]] + 0.05
    assert top(down.probs) == "neutral"
    for k in range(6):  # looking down for a moment
        far = c.observe(t + 0.2 + 0.1 * k, reading(), RELAXED_BS, (0.0, 26.0, 0.0))
    assert far.weight == pytest.approx(0.1) and "looking down" in far.actions
    assert pose_weight(0, 0) == 1.0 and pose_weight(6, 8) == 1.0 and pose_weight(15, 0) == pytest.approx(0.5)


def test_a_clear_expression_is_never_pushed_into_neutral_by_head_pose_or_talking():
    c, t = calibrated()
    for pitch, speaking in ((20.0, False), (25.0, False), (20.0, True)):
        out = c.observe(t, reading(SNARL), SNARL_BS, (0.0, pitch, 0.0), speaking=speaking)
        assert out.probs[I["anger"]] > 0.45 and out.weight <= 0.5, (pitch, speaking)  # it just counts less
        t += 0.1


def test_while_talking_the_mouth_is_not_described():
    c, t = calibrated()
    for k in range(6):
        out = c.observe(t + 0.1 * k, reading(SNARL), SNARL_BS, (0, 0, 0), speaking=True)
    assert not {"baring teeth", "smiling", "lips pressed together", "mouth open"} & set(out.actions)


def test_a_slowly_creeping_expression_is_not_absorbed_into_the_baseline():
    c, t = calibrated()
    for k in range(6000):  # 10 minutes: neutral sinks by 0.4 log-odds per minute, nothing else moves
        c.observe(t, reading(shift={"neutral": -0.4 * k / 600}), RELAXED_BS, (0, 0, 0))
        t += 0.1
    assert np.abs(c.baseline.z - c.baseline.z0).max() <= 1.0 + 1e-9  # bounded drift
    for k in range(6):
        out = c.observe(t + 0.1 * k, reading(SNARL), SNARL_BS, (0, 0, 0))
    assert top(out.probs) == "anger"


def test_a_broken_frame_or_a_missing_pose_does_no_harm():
    c, t = calibrated(pitch=16.0)
    before = c.baseline.z.copy()
    bad = EmotionReading(probs=(0.125,) * 8, valence=float("nan"), arousal=0.1, logits=(float("nan"),) * 8)
    out = c.observe(t, bad, RELAXED_BS, (0.0, 16.0, 0.0))
    assert abs(sum(out.probs) - 1) < 1e-9 and all(np.isfinite(out.probs)) and out.valence is None
    assert np.array_equal(c.baseline.z, before)  # never adapted to it
    huge = c.observe(t + 0.1, reading([900.0, 0, 0, 0, 0, -900.0, 0, 0]), RELAXED_BS, (0.0, 16.0, 0.0))
    assert top(huge.probs) == "anger"  # no overflow
    posed = c.observe(t + 0.2, reading(), RELAXED_BS, None)  # no pose: the calibration pose is assumed
    assert posed.weight == 1.0 and "head tilted back" not in facial_actions(RELAXED_BS, RELAXED_BS, 0.0, 0.0)


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
    c2, t2 = calibrated()
    mouth = reading(shift={"surprise": 3.0, "neutral": -1.0})
    talking = c2.observe(t2, mouth, bs(jawOpen=0.4), (0, 0, 0), speaking=True)
    silent = c2.observe(t2 + 0.1, mouth, bs(jawOpen=0.4), (0, 0, 0))
    assert talking.weight == pytest.approx(0.5)  # while the learner talks frames count half …
    assert talking.probs[I["neutral"]] > silent.probs[I["neutral"]]  # … and need a clearer face
    assert "mouth open" not in talking.actions


def test_the_baseline_follows_slow_drift_but_not_expressions():
    c, t = calibrated()
    before = c.baseline.z.copy()
    for _ in range(300):  # 30 s of a relaxed face in slightly different light
        c.observe(t, reading(shift={"sadness": 0.8}), RELAXED_BS, (0, 0, 0))
        t += 0.1
    moved = np.abs(c.baseline.z - before).max()
    assert 0.05 < moved < 0.8
    frozen = c.baseline.z.copy()
    for _ in range(100):  # a long smile is not absorbed into "neutral"
        c.observe(t, reading(shift={"happiness": 10.0, "neutral": -1.0}), bs(mouthSmileLeft=0.7, mouthSmileRight=0.7),
                  (0, 0, 0))
        t += 0.1
    assert np.allclose(c.baseline.z, frozen)


def test_sensitivity_changes_how_clear_an_expression_must_be():
    probs = {}
    for level in ("calm", "balanced", "expressive"):
        c, t = calibrated(level)
        out = c.observe(t, reading(PRESSED), PRESSED_BS, (0, 0, 0))
        probs[level] = out.probs[I["neutral"]]
    assert probs["calm"] > probs["balanced"] > probs["expressive"]
    assert set(SENSITIVITY) == {"calm", "balanced", "expressive"}


def test_restart_and_sensitivity_switch():
    c, _ = calibrated()
    c.set_sensitivity("calm")
    c.restart()
    assert not c.ready and c.public() == {"state": "collecting", "progress": 0.0, "sensitivity": "calm"}
    c.set_sensitivity("nonsense")
    assert c.level == "calm"


def test_hallmarks_and_actions_are_baseline_relative_and_fit_the_expression():
    base = dict(RELAXED_BS)
    assert all(v == 0 for v in hallmarks(base, base).values())  # the resting face itself shows nothing
    assert facial_actions(bs(browInnerUp=0.3), base) == ["eyebrows raised"]
    assert "looking away from the screen" in facial_actions(base, base, dyaw=25)
    assert facial_actions(SNARL_BS, base)[:2] == ["smiling", "baring teeth"]  # MediaPipe sees stretched lips …
    assert actions_for(["smiling", "baring teeth", "looking down"], "anger") == ["baring teeth", "looking down"]
    assert actions_for(["smiling", "baring teeth"], "neutral") == []  # … the note names only what fits
    assert actions_for(["smiling"], "happiness") == ["smiling"]
    assert neutral_margin(np.array(STERN_REST, dtype=float)) < -4 < -3 < neutral_margin(np.zeros(8)) + 3
