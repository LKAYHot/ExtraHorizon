"""Voice activity detection → utterances, pre-roll, end of speech and the barge-in bar."""

from __future__ import annotations

import numpy as np

from extrahorizon.voice.vad import FRAME_MS, SileroVad, VadSegmenter, to16k

from .conftest import EnergyVad, make_settings, silence_pcm, speech_pcm

S = make_settings()


def run(seg: VadSegmenter, pcm: bytes, strict: bool = False, chunk: int = 1920):
    events = []
    for i in range(0, len(pcm), chunk):
        events += seg.process(pcm[i : i + chunk], strict)
    return events


def test_speech_opens_and_silence_closes_an_utterance_with_preroll():
    seg = VadSegmenter(EnergyVad(), S)
    ev = run(seg, silence_pcm(1.0) + speech_pcm(1.2) + silence_pcm(1.0))
    kinds = [e.kind for e in ev]
    assert kinds.count("start") == 1 and kinds.count("end") == 1
    start = next(e for e in ev if e.kind == "start")
    assert 0.2 <= len(start.audio) / 2 / 24000 <= S.vad_preroll_ms / 1000 + 0.04  # the onset is not lost
    end = next(e for e in ev if e.kind == "end")
    assert 1.0 <= end.duration_ms / 1000 <= 1.3
    audio_s = sum(len(e.audio) for e in ev if e.kind == "audio") / 2 / 24000
    assert audio_s >= 1.2  # the whole utterance goes to speech-to-text


def test_clicks_and_short_noises_do_not_open_an_utterance():
    seg = VadSegmenter(EnergyVad(), S)
    ev = run(seg, silence_pcm(0.5) + speech_pcm(0.1) + silence_pcm(0.5) + speech_pcm(0.12) + silence_pcm(0.5))
    assert [e.kind for e in ev if e.kind != "audio"] == []


def test_a_comma_pause_does_not_end_the_utterance():
    seg = VadSegmenter(EnergyVad(), S)
    ev = run(seg, speech_pcm(0.8) + silence_pcm(0.3) + speech_pcm(0.8) + silence_pcm(1.0))
    assert [e.kind for e in ev if e.kind != "audio"] == ["start", "end"]


def test_barge_in_needs_sustained_speech_while_she_is_audible():
    seg = VadSegmenter(EnergyVad(), S)
    # 250 ms of speech would open an utterance normally …
    assert [e.kind for e in run(seg, speech_pcm(0.26) + silence_pcm(0.2))].count("start") == 1
    seg = VadSegmenter(EnergyVad(), S)
    # … but not while her voice is playing (echo, a cough): barge-in needs ≥ 350 ms at the stricter bar
    assert [e.kind for e in run(seg, speech_pcm(0.26) + silence_pcm(0.2), strict=True)].count("start") == 0
    ev = run(seg, speech_pcm(0.6), strict=True)
    starts = [e for e in ev if e.kind == "start"]
    assert len(starts) == 1 and starts[0].barge is True


def test_very_long_speech_is_cut_into_turns():
    s = make_settings(vad_max_utterance_s=2.0)
    seg = VadSegmenter(EnergyVad(), s)
    ev = run(seg, speech_pcm(5.0))
    assert [e.kind for e in ev].count("end") >= 2


def test_reset_forgets_a_half_open_utterance():
    seg = VadSegmenter(EnergyVad(), S)
    run(seg, speech_pcm(0.5))
    assert seg.in_utt
    seg.reset()
    assert not seg.in_utt and [e.kind for e in run(seg, silence_pcm(1.0))] == []


def test_resampling_keeps_frame_timing():
    x = np.zeros(768, dtype=np.float32)
    assert to16k(x).shape == (512,)
    assert FRAME_MS == 32


def test_silero_scores_silence_low(vad_model_path):
    vad = SileroVad(vad_model_path)
    probs = [vad.prob(np.zeros(512, dtype=np.float32)) for _ in range(20)]
    assert max(probs) < 0.2
    noise = np.random.default_rng(0).normal(0, 0.02, 512 * 30).astype(np.float32)
    probs = [vad.prob(noise[i : i + 512]) for i in range(0, len(noise), 512)]
    assert np.mean(probs) < 0.5  # steady noise is not speech
