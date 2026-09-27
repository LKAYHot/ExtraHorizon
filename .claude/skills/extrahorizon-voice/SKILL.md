---
name: extrahorizon-voice
description: Debug, measure and tune ExtraHorizon's real-time voice conversation — microphone choice and capture (AudioWorklet), Silero VAD turn-taking, OpenAI gpt-live-transcribe speech-to-text, fillers, speculative turns, barge-in, "wait, stop", joined paused sentences, echo guard, the Fish Audio drama-3-preview voice (cues, splitter, silence cap) and the browser player. Use this whenever the voice is slow, silent, cut off, choppy, reads tags or maths aloud, she interrupts herself, does not stop when talked over, answers before the learner finished, mishears words, picks up the wrong microphone, sounds like an assistant instead of a person, or when someone changes the persona's voice cues or asks "почему она молчит / тормозит / перебивает", "голос", "озвучка", "распознавание речи", "выбор микрофона".
---

# The voice pipeline

Read `docs/VOICE.md` first (diagram, turn-taking table, measured latencies). Code: `backend/extrahorizon/live_ws.py`
(turn-taking), `turns.py` (LLM → splitter → Fish → frames), `voice/*.py`, `frontend/src/lib/voice.svelte.js` + `audio.js`.

## Measure before changing anything

1. Offline logic: `cd backend && uv run pytest tests/test_live.py tests/test_vad.py tests/test_voice.py tests/test_stt.py`.
2. Real providers, real VAD, a real spoken WAV streamed like a microphone (server running):
   `uv run python scripts/demo_check.py --runs 2 --speech ../frontend/e2e/.cache/question.wav`
   → `speech_end_to_filler_s` (≈0), `speech_end_to_answer_voice_s` (≈1.7–2.3 s), `heard`, `first_audio_s` for typed.
   Build the WAV with `uv run python scripts/make_fake_mic.py --out ../frontend/e2e/.cache/question.wav` (Windows SAPI, offline).
3. Browser path with a virtual microphone: `cd frontend && npx playwright test --project voice`.
4. Server log (`EH_LOG_LEVEL=info`): `turn N done … ttft=…`, `fish: trimmed … ms of model silence`, `stt error`, `fish:` failures.

## Symptom → cause → knob

| Symptom | Likely cause | Fix |
|---|---|---|
| Long silence before she speaks | LLM TTFT / Fish first chunk | check `ttft` in the log; `EH_TTS_FIRST_CHUNK_CHARS` lower (36 → 28); keep `EH_FISH_LATENCY=balanced`; the warm pool (`EH_FISH_WARM_CONNECTIONS`) must be ≥ 1 |
| Answers too long / lecture-like | persona / reply rules | `context.py` `REPLY_NOTE_*`, persona "about forty-five words" |
| She reads `[tags]`, LaTeX or code aloud | cue outside `[...]` rules / new markup | `voice/tags.py` `speakable()` / `speak_math()`; add a test in `test_voice.py` |
| Multi-second pauses mid-sentence | drama "plays" pauses | `EH_TTS_MAX_SILENCE_MS` (700) / `EH_TTS_MAX_LEADING_SILENCE_MS` (120) |
| Answers before the learner finished | end-of-speech too eager | `EH_VAD_END_SILENCE_MS` 550 → 700; pauses < `EH_VOICE_MERGE_WINDOW_S` are joined anyway |
| She interrupts herself | her voice leaks into the mic | headphones; `EH_BARGE_IN_THRESHOLD` 0.6 → 0.7, `EH_BARGE_IN_MIN_MS` 350 → 500; the echo guard catches transcripts that repeat her words |
| Talking over her doesn't stop her | interruptions turned off (sidebar *Let me interrupt her*, `EH_BARGE_IN=false`) / barge-in bar too high / playback state not reported | the switch; lower the barge-in knobs; check the browser sends `{"type":"playback"}` |
| Other voices in a noisy room cut her off | interruptions are on | turn off *Let me interrupt her* (she finishes; Stop still works) |
| "Wait, stop" starts a new answer | not recognised as a stop command | `STOP_CORE`/`STOP_EXTRA` in `live_ws.py` (+ a case in `test_stop_commands`) |
| Misheard domain words | STT prompt | `EH_STT_PROMPT` vocabulary; `EH_STT_CONTEXT_BIAS=true` adds her last words; `EH_STT_NOISE_REDUCTION=near_field` for headsets |
| Voice cut at the start of a new answer | a stale `audio_stop` for a shared turn | invariant: never `audio_stop` an unreleased speculative speaker (see `Speaker.abort_nowait`) — regression test in `test_live.py` |
| No voice at all | `FISH_API_KEY`, breaker open, speaker muted in the UI | `/api/health` `tts.state`, the speaker toggle, browser autoplay (a click/Enter unlocks audio) |
| Wrong / far microphone (webcam mic), bad transcripts | device choice | the **Microphone** list (sidebar, microphone card, under the chat while talking): `voice.svelte.js` `setDevice()` switches live without resetting STT; `MicCapture` falls back to the default when the device is gone (`OverconstrainedError`/`NotFoundError`) |
| Sounds like an assistant ("Tell me what you were asking…", "How can I help?") | persona | `context.py` WHO YOU ARE / HOW YOU TALK + the banned-phrase list (asserted in `test_context.py`); check with a real-LLM probe through `build_messages()` |

## Invariants

- Only VAD-detected speech (+pre-roll) goes to speech-to-text; mic off = nothing is processed.
- A speculative turn is invisible and silent until confirmed; a mismatch replaces it on the same turn number.
- Barge-in / stop / newer question / reset stop her voice at once; frames of stopped turns are never sent again.
- **Interruptions off** (`{"type":"interruptions","on":false}`, the sidebar's *Let me interrupt her*, remembered in
  the browser): during her turn — thinking, speaking, writing a report silently — speech is held in `_utt_start`
  before it becomes an utterance (no number, no transcription, no answer; `held` → "she finishes first"), a typed
  question waits (`app.waitForHer`); a continuation of the learner's own paused sentence still joins; the Stop button
  always stops her; `EH_BARGE_IN=false` caps it for everyone (tests: `test_with_interruptions_off_*`,
  `test_the_servers_setting_caps_the_browsers_choice`, `voice.test.js`, e2e `demo.spec.js`).
- The first cancel reason wins (`interrupted` keeps the partial answer).
- Fish `drama-*` models only on `/v1/tts/live/with-timestamp` with the `model` header.
- Update `docs/VOICE.md` (and EXTERNAL_DEPENDENCIES.md for provider/model changes) with any behaviour change.
