"""Emotion engine: smoothing over time, unknown handling, stable dominant emotion, and the
plain-English description that goes into the prompt (pure logic, injected clock)."""

from __future__ import annotations

import re

import pytest

from extrahorizon.context import emotion_note
from extrahorizon.emotion.engine import OK, UNKNOWN, EmotionConfig, EmotionEngine, EmotionObservation
from extrahorizon.vision.types import EMOTIONS

CFG = EmotionConfig(alpha=0.35, reference_fps=10, max_gap_s=1.0, switch_hold_s=0.8, switch_margin=0.08, history_s=60)


def dist(main: str, p: float = 0.8, second: str | None = None, q: float = 0.0) -> tuple[float, ...]:
    rest = (1.0 - p - q) / (len(EMOTIONS) - (2 if second else 1))
    out = [rest] * len(EMOTIONS)
    out[EMOTIONS.index(main)] = p
    if second:
        out[EMOTIONS.index(second)] = q
    return tuple(out)


def obs(t: float, main: str = "neutral", p: float = 0.8, v: float | None = 0.0, a: float | None = 0.0, **kw) -> EmotionObservation:
    return EmotionObservation(t, dist(main, p, kw.get("second"), kw.get("q", 0.0)), v, a, OK, None, kw.get("source", "camera"))


def feed(engine: EmotionEngine, main: str, t0: float, seconds: float, fps: float = 10.0, **kw):
    t, out = t0, None
    changes = []
    while t < t0 + seconds - 1e-9:
        out, ch = engine.update(obs(t, main, **kw))
        changes += ch
        t += 1 / fps
    return out, changes, t


def test_first_reading_sets_the_dominant_emotion_at_once():
    e = EmotionEngine(CFG)
    st, changes = e.update(obs(0.0, "happiness", 0.7))
    assert st.status == OK and st.dominant == "happiness"
    assert [c.current for c in changes] == ["happiness"]
    assert abs(sum(st.probs) - 1) < 1e-9


def test_smoothing_is_time_based_not_frame_based():
    """30 fps and 5 fps must converge alike over the same wall-clock time."""
    results = []
    for fps in (30.0, 5.0):
        e = EmotionEngine(CFG)
        feed(e, "neutral", 0.0, 1.0, fps)
        st, _, _ = feed(e, "happiness", 1.0, 0.6, fps)
        results.append(st.probs[EMOTIONS.index("happiness")])
    assert abs(results[0] - results[1]) < 0.08


def test_dominant_switches_only_after_holding_the_lead():
    e = EmotionEngine(CFG)
    feed(e, "neutral", 0.0, 2.0)
    st, changes, t = feed(e, "surprise", 2.0, 0.5)  # a brief flash of surprise
    assert st.dominant == "neutral" and not changes
    st, changes, t = feed(e, "surprise", t, 1.5)
    assert st.dominant == "surprise" and [c.previous for c in changes] == ["neutral"]


def test_close_competitors_do_not_flicker():
    e = EmotionEngine(CFG)
    feed(e, "neutral", 0.0, 1.0, p=0.45, second="happiness", q=0.40)
    st, changes, _ = feed(e, "happiness", 1.0, 3.0, p=0.46, second="neutral", q=0.44)  # lead of 0.02 < margin
    assert st.dominant == "neutral" and not changes


def test_unknown_is_never_neutral_and_restarts_smoothing():
    e = EmotionEngine(CFG)
    feed(e, "happiness", 0.0, 1.0)
    st, changes = e.update(EmotionObservation(1.0, None, status=UNKNOWN, reason="no_face"))
    assert st.status == UNKNOWN and st.reason == "no_face"
    assert st.probs is None and st.dominant is None and st.valence is None
    st, _ = e.update(obs(1.2, "sadness"))  # smoothing restarted: no memory of the happy face
    assert st.dominant == "sadness" and st.probs[EMOTIONS.index("sadness")] == pytest.approx(0.8)


def test_a_long_gap_restarts_smoothing_too():
    e = EmotionEngine(CFG)
    feed(e, "happiness", 0.0, 1.0)
    st, changes = e.update(obs(5.0, "anger"))
    assert st.dominant == "anger" and changes[0].current == "anger"


def test_source_switch_starts_a_new_run():
    e = EmotionEngine(CFG)
    feed(e, "happiness", 0.0, 1.0)
    st, _ = e.update(obs(1.1, "fear", source="simulation"))
    assert st.source == "simulation" and st.dominant == "fear"


def test_description_uses_words_only_and_mentions_the_previous_emotion():
    e = EmotionEngine(CFG)
    _, _, t = feed(e, "neutral", 0.0, 4.0, v=0.0, a=-0.2)
    _, _, t = feed(e, "happiness", t, 3.0, v=0.6, a=0.4)
    ctx = e.describe(t)
    assert ctx["available"] and ctx["dominant"] == "happiness"
    assert "happy" in ctx["text"] and "positive" in ctx["text"] and "high energy" in ctx["text"]
    assert "looked neutral" in ctx["text"]
    note = emotion_note(ctx)
    assert note.startswith("[What you see on the learner's webcam right now]")
    assert not re.search(r"\d", note)  # no numbers → no false precision sent to the model


def test_description_right_after_a_switch_names_the_emotion_just_before():
    e = EmotionEngine(CFG)
    _, _, t = feed(e, "anger", 0.0, 3.0)
    _, _, t = feed(e, "neutral", t, 2.5)
    st, changes, t = feed(e, "happiness", t, 1.5)
    assert st.dominant == "happiness"
    assert "looked neutral" in e.describe(t)["text"]


def test_stale_or_unknown_state_is_not_described():
    e = EmotionEngine(CFG)
    assert e.describe(0.0)["available"] is False
    feed(e, "happiness", 0.0, 1.0)
    assert e.describe(10.0)["available"] is False  # the last reading is too old
    assert emotion_note(e.describe(10.0)) is None


def test_a_weak_expression_is_described_as_neutral_with_a_hint():
    e = EmotionEngine(CFG)
    feed(e, "sadness", 0.0, 1.0, p=0.35, second="neutral", q=0.3)  # below the "clearly there" floor
    text = e.describe(1.0)["text"]
    assert "neutral expression" in text and "a bit of sadness" in text
    e.reset()
    feed(e, "sadness", 0.0, 1.0, p=0.9)
    assert "clearly sad" in e.describe(1.0)["text"]


def test_unreliable_frames_barely_move_the_estimate():
    e = EmotionEngine(CFG)
    feed(e, "neutral", 0.0, 2.0)
    st, _ = e.update(EmotionObservation(2.1, dist("anger", 0.95), 0.0, 0.0, OK, None, "camera", weight=0.1))
    assert st.probs[EMOTIONS.index("anger")] < 0.12 and st.dominant == "neutral"


def test_visible_facial_actions_are_described_in_words():
    e = EmotionEngine(CFG)
    e.update(EmotionObservation(0.0, dist("anger", 0.8), -0.4, 0.3, OK, None, "camera",
                                actions=("frowning, brows pulled down",)))
    assert "Visible right now: frowning, brows pulled down." in e.describe(0.0)["text"]


def test_reset_forgets_everything():
    e = EmotionEngine(CFG)
    feed(e, "happiness", 0.0, 2.0)
    e.reset()
    assert e.last_state is None and e.segments == [] and e.describe(2.0)["available"] is False


def test_simulated_history_never_leaks_into_a_camera_description():
    e = EmotionEngine(CFG)
    _, _, t = feed(e, "happiness", 0.0, 3.0, source="simulation")
    _, _, t = feed(e, "neutral", t, 2.0)  # the real camera takes over
    text = e.describe(t)["text"]
    assert "happy" not in text and e.describe(t)["source"] == "camera"


def test_a_simulated_note_says_so():
    e = EmotionEngine(CFG)
    _, _, t = feed(e, "sadness", 0.0, 2.0, source="simulation")
    note = emotion_note(e.describe(t))
    assert "demo simulation" in note and "camera estimate" not in note
