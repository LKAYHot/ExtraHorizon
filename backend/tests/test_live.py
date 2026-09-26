"""The voice conversation over /api/live, end to end on the real routes and turn logic:
voice activity → speech-to-text → filler → (speculative) turn → LLM → voice → browser,
with barge-in, "wait, stop", continued sentences and echo. Providers are offline doubles
(scripted STT, tone TTS, fake LLM); the VAD is a deterministic energy detector."""

from __future__ import annotations

import json
import struct
import time

import anyio
import pytest
from fastapi.testclient import TestClient

from extrahorizon.app import create_app
from extrahorizon.context import REPLY_NOTE_VOICE
from extrahorizon.voice.fish import MockTts
from extrahorizon.voice.stt import MockStt
from extrahorizon.voice.vad import VadSegmenter

from .conftest import EnergyVad, FakeLLM, FakeVision, make_settings, new_sid, parse_sse, silence_pcm, speech_pcm


class Live:
    """Browser side of /api/live: sends mic audio, collects JSON messages and voice frames."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.msgs: list[dict] = []
        self.audio: dict[int, int] = {}  # turn → bytes of voice received
        self.frames: list[tuple[int, int]] = []  # (index in msgs when received, turn)

    def recv(self, timeout: float = 5.0):
        async def get():
            with anyio.fail_after(timeout):
                return await self.ws._send_rx.receive()

        m = self.ws.portal.call(get)
        if m.get("bytes") is not None:
            turn = struct.unpack(">I", m["bytes"][:4])[0]
            self.audio[turn] = self.audio.get(turn, 0) + len(m["bytes"]) - 4
            self.frames.append((len(self.msgs), turn))
            return None
        msg = json.loads(m["text"])
        self.msgs.append(msg)
        return msg

    def until(self, pred, timeout: float = 8.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            m = self.recv(max(0.05, deadline - time.monotonic()))
            if m is not None and pred(m):
                return m
        raise AssertionError(f"not received; got {[x.get('type') for x in self.msgs][-30:]}")

    def drain(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                self.recv(max(0.01, deadline - time.monotonic()))
            except TimeoutError:
                return

    def say(self, pcm: bytes, chunk: int = 1920) -> None:
        for i in range(0, len(pcm), chunk):
            self.ws.send_bytes(pcm[i : i + chunk])

    def send(self, obj: dict) -> None:
        self.ws.send_text(json.dumps(obj))

    def of(self, msg_type: str, **match) -> list[dict]:
        return [m for m in self.msgs if m.get("type") == msg_type and all(m.get(k) == v for k, v in match.items())]

    def turn_events(self, turn: int) -> list[str]:
        return [m["event"] for m in self.msgs if m.get("type") == "turn" and m["turn_no"] == turn]


def voice_app(script: list[str], llm: FakeLLM | None = None, final_delay: float = 0.05, tts_delay: float = 0.002,
              **settings):
    s = make_settings(**settings)
    llm = llm or FakeLLM()
    app = create_app(
        s, llm=llm, vision=FakeVision(), tts=MockTts(s.tts_sample_rate, delay_s=tts_delay),
        stt_factory=lambda _s: MockStt(script, final_delay_s=final_delay),
        vad_factory=lambda: VadSegmenter(EnergyVad(), s),
    )
    return TestClient(app), llm


def open_live(c: TestClient, sid: str | None = None, mic: bool = True):
    deadline = time.monotonic() + 5
    while c.get("/api/health").json()["fillers"] != "ready" and time.monotonic() < deadline:
        time.sleep(0.02)
    sid = sid or new_sid()
    cm = c.websocket_connect(f"/api/live?session_id={sid}")
    ws = cm.__enter__()
    live = Live(ws)
    hello = live.until(lambda m: m["type"] == "hello")
    assert hello["persona"] == "Rika" and hello["fillers"] == "ready"
    if mic:
        live.send({"type": "mic", "on": True})
    return cm, live, sid


def question(seconds: float = 1.2) -> bytes:
    return speech_pcm(seconds) + silence_pcm(0.8)


# ---------------------------------------------------------------------- a spoken question
def test_spoken_question_gets_filler_then_answer_voice_on_the_same_turn():
    """Regression: when the final transcript differs from the live one, the speculative turn
    is replaced — the filler and the replacement answer (same turn number) must still play."""
    c, llm = voice_app(["Explain recursion to me please."])
    with c:
        cm, live, _ = open_live(c)
        try:
            live.say(question(1.2))
            end = live.until(lambda m: m["type"] == "vad" and m["speaking"] is False)
            turn = end["turn_no"]
            live.until(lambda m: m["type"] == "turn" and m["event"] == "done")
            live.until(lambda m: m["type"] == "audio_end" and m["turn_no"] == turn)
            filler = live.of("filler", turn_no=turn)
            assert filler and live.of("audio_begin", turn_no=turn, kind="filler")
            assert live.of("audio_begin", turn_no=turn, kind="answer")
            assert live.of("heard")[0]["text"] == "Explain recursion to me please."
            assert not live.of("audio_stop")  # nothing was cut
            assert live.audio[turn] > 44100 * 2 * 0.5  # filler + answer voice arrived
            assert live.turn_events(turn) == ["meta"] + ["delta"] * live.turn_events(turn).count("delta") + ["done"]
            meta = [m for m in live.msgs if m.get("type") == "turn" and m["event"] == "meta"][0]
            assert meta["data"]["user_message"]["source"] == "voice"
            assert len(llm.requests) == 2  # the speculative start on "Explain recursion to" + the real one
            assert {"role": "system", "content": REPLY_NOTE_VOICE} in llm.requests[-1]
            assert llm.requests[-1][-1]["content"] == "Explain recursion to me please."
        finally:
            cm.__exit__(None, None, None)


def test_a_finished_speculative_answer_is_not_committed_when_the_final_transcript_differs():
    """The LLM may finish the speculative answer before the final transcript arrives: it must
    wait for confirmation, and a mismatch must leave no trace in the history."""
    c, llm = voice_app(["Explain recursion to me please."], final_delay=0.4)
    with c:
        cm, live, sid = open_live(c)
        try:
            live.say(question(1.2))
            live.until(lambda m: m["type"] == "turn" and m["event"] == "done")
            live.drain(0.3)
            st = c.get(f"/api/session/{sid}/state").json()
            assert [m["role"] for m in st["messages"]] == ["user", "assistant"]
            assert st["messages"][0]["text"] == "Explain recursion to me please."
            assert len(llm.requests) == 2
            assert not [m for m in live.msgs if m.get("type") == "turn" and m["event"] == "meta"
                        and m["data"]["user_message"]["text"] != "Explain recursion to me please."]
        finally:
            cm.__exit__(None, None, None)


def test_speculation_that_matches_the_final_transcript_is_released():
    c, llm = voice_app(["Explain recursion."])
    with c:
        cm, live, sid = open_live(c)
        try:
            live.say(question(1.2))
            live.until(lambda m: m["type"] == "turn" and m["event"] == "done")
            assert len(llm.requests) == 1  # no second LLM call: the live transcript was right
            st = c.get(f"/api/session/{sid}/state").json()
            assert [m["role"] for m in st["messages"]] == ["user", "assistant"]
            assert st["messages"][0]["text"] == "Explain recursion." and st["messages"][0]["source"] == "voice"
        finally:
            cm.__exit__(None, None, None)


def test_an_llm_error_during_speculation_is_shown_once_the_question_is_confirmed():
    c, llm = voice_app(["Explain recursion."], llm=FakeLLM(script=["error", "ok"]))
    with c:
        cm, live, sid = open_live(c)
        try:
            live.say(question(1.2))
            err = live.until(lambda m: m["type"] == "turn" and m["event"] == "error")
            assert err["data"]["retryable"] is True
            assert live.turn_events(err["turn_no"])[0] == "meta"  # the learner sees the question and the error
            assert c.get(f"/api/session/{sid}/state").json()["messages"] == []
        finally:
            cm.__exit__(None, None, None)


# ---------------------------------------------------------------------- interruptions
def test_barge_in_stops_her_voice_keeps_the_partial_answer_and_wait_stop_only_stops():
    long = " ".join(["[calm] Recursion means a function calls itself on a smaller input."] * 8)
    c, llm = voice_app(["Explain recursion to me please.", "Wait, stop."], llm=FakeLLM(script=["slow", "slow"], text=long),
                       llm_idle_timeout_s=2.0, llm_first_token_timeout_s=2.0)
    with c:
        cm, live, sid = open_live(c)
        try:
            live.say(question(1.2))
            begin = live.until(lambda m: m["type"] == "audio_begin" and m["kind"] == "answer")
            turn = begin["turn_no"]
            live.send({"type": "playback", "playing": True})  # the browser is playing her voice
            live.drain(0.1)
            live.say(speech_pcm(0.8) + silence_pcm(0.8))  # the learner talks over her
            barge = live.until(lambda m: m["type"] == "barge_in")
            assert barge["by"] == "voice"
            assert live.of("audio_stop", turn_no=turn)
            interrupted = live.until(lambda m: m["type"] == "turn" and m["event"] == "interrupted")
            assert interrupted["turn_no"] == turn and interrupted["data"]["interrupted"] is True
            ignored = live.until(lambda m: m["type"] == "stt_ignored")
            assert ignored["reason"] == "stop" and ignored["text"] == "Wait, stop."
            live.drain(0.3)
            assert len(llm.requests) == 2  # the barge-in utterance started no new answer
            st = c.get(f"/api/session/{sid}/state").json()
            assert st["messages"][-1]["interrupted"] is True
            assert 0 < len(st["messages"][-1]["text"]) < len(long)
        finally:
            cm.__exit__(None, None, None)


def test_a_pause_mid_sentence_continues_the_same_question():
    c, llm = voice_app(["Explain recursion", "and give me an example."],
                       llm=FakeLLM(script=["hang", "hang", "ok", "ok"]), llm_first_token_timeout_s=3.0)
    with c:
        cm, live, _ = open_live(c)
        try:
            live.say(speech_pcm(0.8) + silence_pcm(0.7))  # "Explain recursion" … (a pause)
            live.until(lambda m: m["type"] == "vad" and m["speaking"] is False)
            live.say(speech_pcm(1.0) + silence_pcm(0.8))  # … "and give me an example."
            start2 = live.until(lambda m: m["type"] == "vad" and m["speaking"] is True)
            assert start2["continues"] == 1 and start2["barge"] is False
            heard = live.until(lambda m: m["type"] == "heard")
            assert heard["text"] == "Explain recursion and give me an example."
            live.until(lambda m: m["type"] == "turn" and m["event"] == "done")
            assert llm.requests[-1][-1]["content"] == "Explain recursion and give me an example."
            metas = [m for m in live.msgs if m.get("type") == "turn" and m["event"] == "meta"]
            assert [m["data"]["user_message"]["text"] for m in metas][-1] == "Explain recursion and give me an example."
        finally:
            cm.__exit__(None, None, None)


def test_a_pause_after_a_fast_answer_that_was_not_heard_yet_still_joins_the_sentence():
    """A fast LLM can finish (and commit) the answer to the first half before the learner
    goes on; as long as none of it was heard, it is taken back and the halves are joined."""
    c, llm = voice_app(["Explain recursion", "and give me an example."], tts_delay=0.8)
    with c:
        cm, live, sid = open_live(c)
        try:
            live.say(speech_pcm(0.8) + silence_pcm(0.7))
            first = live.until(lambda m: m["type"] == "turn" and m["event"] == "done")  # answered in text…
            live.say(speech_pcm(1.0) + silence_pcm(0.8))  # … but not heard yet: the learner goes on
            dropped = live.until(lambda m: m["type"] == "turn" and m["event"] == "dropped")
            assert dropped["turn_no"] == first["turn_no"] and dropped["data"]["reason"] == "merged"
            heard = live.until(lambda m: m["type"] == "heard")
            assert heard["text"] == "Explain recursion and give me an example."
            live.until(lambda m: m["type"] == "turn" and m["event"] == "done" and m["turn_no"] != first["turn_no"])
            st = c.get(f"/api/session/{sid}/state").json()
            assert [m["text"] for m in st["messages"] if m["role"] == "user"] == ["Explain recursion and give me an example."]
        finally:
            cm.__exit__(None, None, None)


def test_her_own_voice_picked_up_by_the_mic_is_ignored_as_echo():
    text = "[calm] Recursion is a function calling itself until it reaches the base case."
    c, llm = voice_app(["Explain recursion.", "a function calling itself until it reaches the base case"],
                       llm=FakeLLM(text=text), voice_merge_window_s=0.2)
    with c:
        cm, live, _ = open_live(c)
        try:
            live.say(question(1.2))
            live.until(lambda m: m["type"] == "audio_end")
            live.send({"type": "playback", "playing": True})
            live.drain(0.3)
            live.say(speech_pcm(1.2) + silence_pcm(0.8))
            ignored = live.until(lambda m: m["type"] == "stt_ignored")
            assert ignored["reason"] == "echo"
            live.drain(0.2)
            assert len(llm.requests) == 1
        finally:
            cm.__exit__(None, None, None)


def test_stop_button_over_the_socket():
    long = " ".join(["[calm] Recursion means a function calls itself."] * 10)
    c, _ = voice_app(["Explain recursion."], llm=FakeLLM(script=["slow"], text=long), llm_idle_timeout_s=2.0)
    with c:
        cm, live, _ = open_live(c)
        try:
            live.say(question(1.2))
            live.until(lambda m: m["type"] == "turn" and m["event"] == "delta")
            live.send({"type": "interrupt"})
            assert live.until(lambda m: m["type"] == "barge_in")["by"] == "button"
            assert live.until(lambda m: m["type"] == "turn" and m["event"] in ("interrupted", "done"))["event"] == "interrupted"
        finally:
            cm.__exit__(None, None, None)


def test_stop_while_she_is_still_thinking_cancels_the_question_for_good():
    """Review finding: Stop pressed before the final transcript used to commit a phantom
    exchange and then answer anyway once the transcript arrived."""
    long = " ".join(["[calm] Recursion means a function calls itself on a smaller input."] * 8)
    c, llm = voice_app(["Explain recursion."], llm=FakeLLM(script=["slow", "slow"], text=long),
                       final_delay=0.6, llm_idle_timeout_s=2.0)
    with c:
        cm, live, sid = open_live(c)
        try:
            live.say(question(1.2))
            live.until(lambda m: m["type"] == "filler")
            live.send({"type": "interrupt"})
            assert live.until(lambda m: m["type"] == "barge_in")["by"] == "button"
            ignored = live.until(lambda m: m["type"] == "stt_ignored")
            assert ignored["reason"] == "stopped" and ignored["text"] == "Explain recursion."
            live.drain(0.4)
            assert not [m for m in live.msgs if m.get("type") == "turn" and m["event"] == "meta"]
            assert c.get(f"/api/session/{sid}/state").json()["messages"] == []
            assert len(llm.requests) == 1  # only the speculative start, nothing after Stop
        finally:
            cm.__exit__(None, None, None)


def test_a_new_session_drops_a_question_still_being_transcribed():
    c, llm = voice_app(["Explain recursion to me please."], final_delay=0.6)
    with c:
        cm, live, sid = open_live(c)
        try:
            live.say(question(1.2))
            live.until(lambda m: m["type"] == "vad" and m["speaking"] is False)
            assert c.post("/api/session/reset", json={"session_id": sid}).json()["ok"] is True
            live.until(lambda m: m["type"] == "reset")
            live.drain(1.0)  # the transcript arrives after the reset …
            assert not [m for m in live.msgs if m.get("type") in ("heard", "turn")]  # … and starts nothing
            assert c.get(f"/api/session/{sid}/state").json()["messages"] == []
        finally:
            cm.__exit__(None, None, None)


def test_echo_needs_her_phrasing_not_just_her_words():
    from extrahorizon.live_ws import echo_ratio

    said = "[calm] You need a base case, otherwise the function keeps calling itself forever."
    assert echo_ratio("What is a base case?", said) < 0.6  # a real follow-up question
    assert echo_ratio("the function keeps calling itself forever", said) >= 0.6  # her own voice
    assert echo_ratio("ok", said) == 0.0


# ---------------------------------------------------------------------- options
def test_text_only_mode_sends_no_voice():
    c, _ = voice_app(["Explain recursion."])
    with c:
        cm, live, _ = open_live(c)
        try:
            live.send({"type": "voice_out", "on": False})
            live.say(question(1.2))
            live.until(lambda m: m["type"] == "turn" and m["event"] == "done")
            live.drain(0.3)
            assert live.audio == {} and not live.of("filler")
        finally:
            cm.__exit__(None, None, None)


def test_microphone_off_means_nothing_is_listened_to():
    c, llm = voice_app(["Explain recursion."])
    with c:
        cm, live, _ = open_live(c, mic=False)
        try:
            live.say(question(1.2))
            live.drain(0.5)
            assert not live.of("vad") and llm.requests == []
        finally:
            cm.__exit__(None, None, None)


def test_typed_question_is_spoken_on_the_voice_socket_and_can_be_stopped():
    long = " ".join(["[calm] Recursion means a function calls itself."] * 12)
    c, _ = voice_app(["unused"], llm=FakeLLM(script=["ok", "slow"], text=long), llm_idle_timeout_s=2.0)
    with c:
        cm, live, sid = open_live(c, mic=False)
        try:
            r = c.post("/api/chat", json={"session_id": sid, "message": "Explain recursion."})
            ev = parse_sse(r.text)
            meta, done = ev[0][1], ev[-1]
            assert done[0] == "done" and meta["voice"] is True
            live.until(lambda m: m["type"] == "audio_end" and m["turn_no"] == meta["turn_no"])
            assert live.audio[meta["turn_no"]] > 0
            assert meta["emotion_context"]["available"] is False  # no camera → nothing about a face was sent
        finally:
            cm.__exit__(None, None, None)


def test_rest_interrupt_ends_a_typed_answer_as_interrupted():
    import threading

    long = " ".join(["[calm] Recursion means a function calls itself."] * 20)
    c, _ = voice_app(["unused"], llm=FakeLLM(script=["slow"], text=long), llm_idle_timeout_s=2.0)
    with c:
        sid = new_sid()
        result: dict = {}

        def ask():
            result["events"] = parse_sse(c.post("/api/chat", json={"session_id": sid, "message": "Explain."}).text)

        t = threading.Thread(target=ask)
        t.start()
        time.sleep(0.4)
        assert c.post("/api/session/interrupt", json={"session_id": sid}).json()["stopped"] is True
        t.join(5)
        names = [n for n, _ in result["events"]]
        assert names[0] == "meta" and names[-1] == "interrupted"
        st = c.get(f"/api/session/{sid}/state").json()
        assert st["messages"][-1]["interrupted"] is True


@pytest.mark.parametrize("text,stop", [
    ("Wait, stop.", True), ("stop", True), ("Hold on a second.", True), ("Стоп, подожди.", True),
    ("Okay stop please", True), ("Wait, what is a base case?", False), ("No", False), ("Stop the loop how?", False),
])
def test_stop_commands(text, stop):
    from extrahorizon.live_ws import is_stop_command

    assert is_stop_command(text) is stop


def test_joining_a_sentence_the_learner_paused_in():
    from extrahorizon.live_ws import join_speech

    assert join_speech(["Explain recursion to me", "And give an example."]) == "Explain recursion to me and give an example."
    assert join_speech(["Wait, stop.", "Can you repeat?"]) == "Wait, stop. Can you repeat?"
    assert join_speech(["So", "I think it works"]) == "So I think it works"
    assert join_speech(["", "Hello"]) == "Hello"
