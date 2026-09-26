# Voice pipeline — how talking to Rika works

Goal: a conversation that feels live. She answers fast, never leaves dead air, stops the moment
you talk over her, and does not cut you off when you pause to think. English is the working
language (the hackathon is in English); Russian is understood.

```
mic ─ getUserMedia (the chosen device, echo cancellation, noise suppression, AGC)
    ─ AudioWorklet: float → PCM16, 24 kHz, 40 ms frames ─ WS /api/live (binary)
         │
         ▼ backend (per connection)
    Silero VAD (ONNX, 32 ms windows)  ─ segmenter: start ≥220 ms speech (leaky) · end 550 ms silence
         │                                         · 400 ms pre-roll · strict bar while she is audible
         ├─ speech frames only ──────────────────▶ OpenAI Realtime transcription (gpt-live-transcribe)
         │                                         partials while you speak · final ≈0.35–0.55 s after commit
         ▼
    turn logic (live_ws.py) ── filler clip at end of speech (cached Fish audio, instant)
                             ── speculative turn on the live transcript (released if the final agrees)
                             ── barge-in · "wait, stop" · continued sentence · echo guard
         ▼
    TurnRunner (turns.py) ─ LLM stream ─ TtsSplitter ─ Fish Audio live WS (drama-3-preview) ─ SilenceCap
         ▼
    PCM16 44.1 kHz frames, 4-byte turn number header ─ browser TtsPlayer (gapless WebAudio, instant stop)
```

## Turn-taking rules

| Situation | What happens | Why |
|---|---|---|
| You stop talking (550 ms of silence) | the utterance is committed to STT; **a filler** ("Hmm…", "Hmph.", "Uhh… let me see.") plays **immediately**; if the live transcript already has ≥2 words, **a speculative turn starts** on it | covers transcription + first token + first audio (~1.5–2 s) with something natural; speculation saves the transcription wait when the live transcript was right |
| The final transcript arrives | same words (normalised) → the speculative turn is **released** (text + voice); different → it is dropped silently and a new turn starts on the final text, **same turn number** (the filler keeps playing, the new answer follows it) | never answer a misheard question |
| You talk while she speaks | while her voice is audible the VAD needs a stricter bar (prob ≥ 0.6 for ≥ 350 ms); then **barge-in**: her audio stops in the browser at once, the answer in progress is kept as *interrupted*, and your words become the next question | responsive, but her own voice / a cough doesn't interrupt her |
| You only said "wait", "stop", "hold on", "стоп", … while interrupting | she stops and **does not** start a new answer | a stop command is not a question |
| You paused mid-sentence and went on (within 3 s, before she started answering aloud) | the pending turn and its filler are dropped — even an answer already written but not yet heard is taken back — and the transcripts are **joined** ("Explain recursion to me" + "and give an example") | thinking pauses are normal |
| The transcript repeats what she was just saying (≥60 % of the words) | ignored as **echo** (and no speculative LLM call is made on it) | her voice leaking from the speakers |
| No transcript within 3 s | the live transcript is used | never hang on a lost event |
| Stop button / Esc | same as barge-in (server-side interrupt, audio stopped locally at once); a question still waiting for its transcript is cancelled too — Stop means stop | |
| A typed question while the socket is open | answered in text (SSE) **and** spoken on the voice socket | one voice for everything |

## Speaking: LLM text → Fish Audio

* **Persona & cues** (`context.py`): every sentence starts with one square-bracket delivery cue
  (`[huffy and flustered]`, `[smug, teasing]`, `[soft and embarrassed, quieter]`), sounds like `[sighing]`
  `[chuckling]`, pauses `[break]`, `[emphasis]` before a key word — following Fish Audio's emotion-control guide.
  A per-turn *reply rules* note keeps answers to two or three short sentences and forbids LaTeX
  (formulas are said in words).
* **Splitter** (`voice/splitter.py`): the first chunk leaves at the first clause boundary after ~36
  characters (or ~72 without one) so the voice starts early; later chunks are whole sentences up to ~140
  characters. It never cuts inside a `[cue]` or a code fence, glues cue-only pieces to the next words and —
  because drama-3 applies a delivery cue only to its own chunk — repeats the last delivery cue on a continuation.
  Markdown and code are removed; LaTeX/maths becomes words ("t squared", "a over b").
* **Fish client** (`voice/fish.py`): `wss://api.fish.audio/v1/tts/live/with-timestamp` with the `model:
  drama-3-preview` header (the only endpoint serving drama models), `latency: balanced`, PCM 44.1 kHz; a warm
  pre-connected socket; the `start` event is sent when the turn begins so the voice loads while the LLM writes;
  `SilenceCap` trims drama's occasional multi-second pauses (lead ≤120 ms, inside ≤700 ms); a watchdog ends a
  reply whose server went silent; a breaker stops redialling a failing service for 30 s.
* **Fillers** (`voice/fillers.py`): nine short lines in the same voice, synthesized once at start-up and cached
  on disk; picked without repeats, softer when the learner looks sad/anxious/angry, playful when happy.

## Measured (real providers, Windows laptop, 2026-09-26)

| Step | Value |
|---|---|
| End of speech → filler starts | at the end-of-speech decision (550 ms of silence after the last word) |
| End-of-speech decision → final transcript | 0.35–0.55 s |
| End-of-speech decision → first sound of the answer (spoken question) | 1.66–2.34 s (median ≈1.9 s over 5 turns) |
| Typed question → first token / first sound | 0.63–0.89 s / 1.5–1.9 s |
| You start talking over her → her audio stops | ≈0.7 s (0.35 s strict VAD + frame batching) |
| Noisy speech (pink noise, SNR ≈5 dB) | transcribed correctly in English and Russian |
| Answer length after the reply rules | 48–63 words, 3 sentences, English even for a Russian question |

Numbers come from `backend/scripts/demo_check.py` and the development probes (browser-like clients streaming
recorded speech in real time). They depend on network and provider load.

## Tuning

`EH_VAD_END_SILENCE_MS` (faster vs. fewer cut-offs), `EH_BARGE_IN_THRESHOLD` / `EH_BARGE_IN_MIN_MS`
(interruptibility vs. echo), `EH_VOICE_MERGE_WINDOW_S`, `EH_FILLER_MIN_UTTERANCE_MS`, `EH_STT_NOISE_REDUCTION`
(`near_field` for a headset), `EH_TTS_FIRST_CHUNK_CHARS`, `EH_FISH_TEMPERATURE`, `EH_FISH_TOP_P`. Headphones
remove echo entirely; with laptop speakers the browser's echo cancellation plus the strict barge-in bar and the
echo guard keep her from interrupting herself.

## Known limits

* Speculation only pays off when the live transcript already contains the last word at the end of speech;
  otherwise the answer starts after the final transcript (still covered by the filler).
* Barge-in needs ~350 ms of clear speech while she is audible; very short interjections ("no!") may not stop her.
* The persona speaks English; if asked explicitly she can answer in Russian (the drama voice then may sound less natural).
