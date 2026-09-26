"""State engine: the rules that decide whether the demo adapts (spec §7.1)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from extrahorizon.engine import (
    OK,
    POSSIBLE_CONFUSION,
    SIGNAL_DECREASED,
    UNKNOWN,
    EngineConfig,
    Observation,
    StateEngine,
)
from extrahorizon.sessions import Session

from .conftest import make_settings, new_sid

CFG = EngineConfig()  # spec defaults: alpha .2 @10 fps, threshold .65, hold 2 s, cooldown 15 s


def feed(engine: StateEngine, values, *, t0: float = 0.0, dt: float = 0.1, source: str = "camera"):
    """Feed values (None = no usable face) at a fixed rate; return (events, next_t)."""
    events, t = [], t0
    for v in values:
        obs = Observation(t, v, OK if v is not None else UNKNOWN, None if v is not None else "no_face", source)
        _, evs = engine.update(obs)
        events += evs
        t += dt
    return events, t


def confusion(events):
    return [e for e in events if e.kind == POSSIBLE_CONFUSION]


def test_short_spike_does_not_trigger():
    e = StateEngine(CFG)
    events, _ = feed(e, [0.1] * 20 + [1.0] * 12 + [0.1] * 40)  # 1.2 s spike
    assert confusion(events) == []


def test_sustained_signal_triggers_exactly_one_event():
    e = StateEngine(CFG)
    events, _ = feed(e, [0.9] * 80)  # 8 s continuously high
    fired = confusion(events)
    assert len(fired) == 1
    assert fired[0].held_s >= CFG.hold_s
    assert fired[0].smoothed > CFG.threshold


def test_event_fires_after_two_seconds_of_wall_clock_time():
    e = StateEngine(CFG)
    fired_at, t = None, 0.0
    while t < 3.0:
        _, evs = e.update(Observation(t, 0.9))
        if evs and fired_at is None:
            fired_at = t
        t += 0.05
    assert fired_at is not None and 2.0 <= fired_at <= 2.1


def test_duration_is_measured_in_time_not_frames():
    # 90 frames in 1.5 s (60 fps): plenty of frames, not enough time
    fast = StateEngine(CFG)
    events, _ = feed(fast, [0.9] * 90, dt=1 / 60)
    assert confusion(events) == []
    # 7 frames spanning 2.4 s (2.5 fps) with a gap limit that tolerates it: enough time
    slow = StateEngine(replace(CFG, max_gap_s=1.0))
    events, _ = feed(slow, [0.9] * 7, dt=0.4)
    assert len(confusion(events)) == 1


def test_one_event_per_episode_even_long_after_the_cooldown():
    e = StateEngine(CFG)
    events, t = feed(e, [0.9] * 160)  # 16 s high: event at 2 s, cooldown until 17 s
    assert len(confusion(events)) == 1
    state = e.last_state
    assert state.cooldown_left_s > 0 and state.held_s == 0 and state.armed is False
    events, t = feed(e, [0.9] * 60, t0=t)  # still tense long after the cooldown: no nagging
    assert confusion(events) == [] and e.last_state.armed is False


def test_a_real_drop_ends_the_episode_and_cooldown_still_applies():
    e = StateEngine(CFG)
    events, t = feed(e, [0.9] * 30)  # event at 2 s, cooldown until 17 s
    assert len(confusion(events)) == 1
    events, t = feed(e, [0.1] * 30, t0=t)  # smoothed falls below the re-arm level
    assert e.last_state.armed is True
    events, t = feed(e, [0.9] * 25, t0=t)  # a new rise inside the cooldown: suppressed
    assert confusion(events) == []
    events, _ = feed(e, [0.9] * 150, t0=t)  # cooldown ends at 17 s → fresh 2 s hold → one event
    assert len(confusion(events)) == 1


def test_a_new_answer_rearms_while_the_face_stays_tense():
    e = StateEngine(CFG)
    events, t = feed(e, [0.9] * 30)
    e.rearm()  # e.g. the adapted answer arrived and the learner still looks confused
    events, _ = feed(e, [0.9] * 170, t0=t)  # cooldown ends at 17 s → fresh hold → event at 19 s
    assert len(confusion(events)) == 1


def test_dip_below_threshold_resets_the_hold_timer():
    e = StateEngine(replace(CFG, alpha=1.0))  # no smoothing: isolates the timer rule
    events, _ = feed(e, [0.9] * 15 + [0.3] * 2 + [0.9] * 15)  # 1.5 s + dip + 1.5 s
    assert confusion(events) == []


def test_unknown_resets_hold_and_smoothing_and_is_never_neutral():
    e = StateEngine(CFG)
    events, t = feed(e, [0.9] * 15)  # 1.5 s above threshold
    state, evs = e.update(Observation(t, None, UNKNOWN, "no_face"))
    assert state.status == UNKNOWN and state.reason == "no_face"
    assert state.smoothed is None and state.raw is None and state.held_s == 0
    more, _ = feed(e, [0.9] * 15, t0=t + 0.1)  # another 1.5 s: must start from zero
    assert confusion(events + evs + more) == []


@pytest.mark.parametrize("reason", ["multiple_faces", "face_too_small", "head_turned", "too_dark", "calibrating"])
def test_low_quality_observations_never_count_even_with_a_value(reason):
    e = StateEngine(CFG)
    status = "calibrating" if reason == "calibrating" else UNKNOWN
    evs = []
    for i in range(60):
        _, ev = e.update(Observation(i * 0.1, 0.95, status, reason))
        evs += ev
    assert evs == [] and e.last_state.smoothed is None and e.last_state.reason == reason


def test_data_gap_counts_as_unknown():
    e = StateEngine(CFG)
    events, t = feed(e, [0.9] * 15)  # 1.5 s
    more, _ = feed(e, [0.9] * 8, t0=t + 1.0)  # 1 s without data (> max_gap), then 0.8 s
    assert confusion(events + more) == []


def test_ema_is_frame_rate_independent():
    slow, fast = StateEngine(replace(CFG, threshold=2.0)), StateEngine(replace(CFG, threshold=2.0))
    slow.update(Observation(0.0, 0.0))
    fast.update(Observation(0.0, 0.0))
    feed(slow, [1.0] * 10, t0=0.1, dt=0.1)  # 10 fps for 1 s
    feed(fast, [1.0] * 30, t0=1 / 30, dt=1 / 30)  # 30 fps for 1 s
    expected = 1 - (1 - CFG.alpha) ** 10
    assert slow.last_state.smoothed == pytest.approx(expected, abs=1e-6)
    assert fast.last_state.smoothed == pytest.approx(expected, abs=1e-6)


def test_switching_to_simulation_does_not_carry_camera_state_over():
    e = StateEngine(CFG)
    events, t = feed(e, [0.9] * 15)  # 1.5 s from the camera
    more, _ = feed(e, [0.9] * 15, t0=t, source="simulation")  # 1.5 s simulated
    assert confusion(events + more) == []


def test_decrease_is_reported_only_when_observed():
    e = StateEngine(CFG)
    events, t = feed(e, [0.9] * 25)
    assert len(confusion(events)) == 1
    e.arm_relief(t)
    still_high, t = feed(e, [0.9] * 30, t0=t)
    assert [x for x in still_high if x.kind == SIGNAL_DECREASED] == []
    unknown, t = feed(e, [None] * 30, t0=t)  # face gone: nothing can be claimed
    assert [x for x in unknown if x.kind == SIGNAL_DECREASED] == []
    low, _ = feed(e, [0.05] * 40, t0=t)  # really measured low for > 2 s
    assert len([x for x in low if x.kind == SIGNAL_DECREASED]) == 1


def test_decrease_window_expires_without_a_claim():
    e = StateEngine(replace(CFG, relief_window_s=1.0))
    e.arm_relief(0.0)
    events, _ = feed(e, [0.05] * 40, t0=1.5)  # low, but only after the window closed
    assert events == []


def test_two_sessions_are_isolated():
    settings = make_settings()
    a, b = Session(new_sid(), settings), Session(new_sid(), settings)
    t, out_a, out_b = 0.0, [], []
    for _ in range(12):  # 1.2 s > hold 0.3 s (test timings)
        out_a += a.ingest_sim(0.95, t, int(t * 1000))
        out_b += b.ingest_sim(0.05, t, int(t * 1000))
        t += 0.1
    assert any(m["type"] == "event" for m in out_a)
    assert not any(m["type"] == "event" for m in out_b)
    assert b.engine.last_state.smoothed < 0.1
    a.reset()
    assert a.engine.last_state is None and a.events == {} and len(a.timeline) == 0
    assert b.engine.last_state is not None and len(b.timeline) == 12


def test_a_frame_in_flight_after_camera_off_does_not_overwrite_the_state():
    from extrahorizon.vision.types import FrameResult

    s = Session(new_sid(), make_settings())
    s.camera_status("off", 1.0, 1000)
    out = s.ingest_frame(5, FrameResult(ok=True, faces=0), 1.1, 1100)
    assert out == [{"type": "tick", "seq": 5, "t": 1100, "vision": None, "engine": None}]  # ack only
    assert s.engine.last_state.reason == "camera_off"
