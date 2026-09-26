# ExtraHorizon — architecture

```
┌──────────────────────────── Browser tab (SvelteKit SPA, Svelte 5) ─────────────────────────────┐
│ Sidebar: brand · New session · Rika persona · subject · microphone · voice cues · status       │
│ Chat: header orb (listening / hearing / thinking / speaking) · messages with voice-cue chips,  │
│       "spoken" / "interrupted" / "speaking" tags, the expression note sent with each answer    │
│       composer: mic toggle (hands-free) · live caption · filler · Stop (Esc) · typed chat (SSE) │
│ Expression panel: camera + labelled face box · Recalibrate · expression now (8 bars,           │
│       sensitivity Calm/Balanced/Expressive, calibration progress) · mood map ·                 │
│       stacked timeline (+ table) · "What Rika is told" · Demo simulation · privacy             │
│ VisionController: getUserMedia → OffscreenCanvas 480 px → JPEG → [seq|jpeg] ─ WS /api/vision │
│ VoiceController:  getUserMedia(chosen mic, AEC, NS, AGC) → AudioWorklet → PCM16 24 kHz ─ WS    │
│                   /api/live · device list (enumerateDevices, devicechange, live switch)        │
│                   TtsPlayer: turn-tagged PCM → gapless WebAudio, instant stop                  │
└──────────────┬───────────────────────────────┬─────────────────────────────▲──────────────────┘
   localhost   │ WS /api/vision                │ WS /api/live (both ways)    │ SSE /api/chat
               ▼                               ▼                             │
┌────────────────────────────── Python process (FastAPI + uvicorn) ────────────────────────────────┐
│ OriginGuard + TrustedHost (no cross-site driving of the tutor, camera or microphone sockets)       │
│ VisionConnection: latest-frame-wins → FaceAnalyzer (MediaPipe + EmotiEffLib ONNX, thread pool;    │
│   face aligned upright + mirror averaged) → quality gates → Session.calib (Calibrator: baseline,    │
│   bias correction, blendshape evidence, pose weight) → Session.emotion (EmotionEngine)             │
│   → tick / calibration / emotion_note / marker                                                     │
│ LiveConnection: VadSegmenter (Silero ONNX) → utterances → OpenAIRealtimeStt (speech only)          │
│   → turn logic: FillerBank · speculative ChatPlan (gated) · confirm/replace · barge-in ·           │
│     stop commands · continued sentences · echo guard · final-transcript watchdog                   │
│ TurnRunner (one turn): LLM stream → deltas → Speaker (TtsSplitter → FishSession → SilenceCap)     │
│   → audio frames on the live socket; commit on done / interrupted; nothing on errors              │
│ SessionStore (per tab, in memory, TTL/LRU): history · calibration · emotion engine · timeline ·   │
│   plan · speaker                                                                                   │
│ Serves frontend/build · health · reset · interrupt · state                                        │
└───────┬───────────────────────────────┬──────────────────────────────────┬─────────────────────────┘
        │ speech segments (PCM)          │ chat text + expression note      │ answer text with voice cues
        ▼                                ▼                                  ▼
 OpenAI Realtime transcription    OpenAI Chat Completions (stream)    Fish Audio live TTS (WebSocket)
 gpt-live-transcribe               gpt-6-luna (fallback gpt-5.5)       drama-3-preview, voice c5d8…
```

## Data flow of the key chains

1. **Camera → expression.** The browser keeps one frame in flight; the backend analyses it in a worker thread
   (MediaPipe ≈7–15 ms + expression model ≈10 ms for the aligned crop and its mirror), gates quality, and answers
   with a `tick`. Frames are never queued, stored or forwarded.
2. **Calibration.** Per session the first ~2.5 s of a relaxed face become the learner's baseline (status
   `calibrating` meanwhile). Every later frame is read relative to it: logits re-centred, each non-neutral class
   backed by baseline-relative facial actions (blendshapes), weighted down when the head moves away from the
   calibration pose or the learner is talking. Recalibrate / sensitivity arrive over the same socket
   (see [EMOTIONS.md](EMOTIONS.md), [CONTRACT.md](CONTRACT.md)).
3. **Expression → prompt.** The engine keeps a smoothed distribution and a stable dominant expression; `describe()`
   turns it into words (+ visible facial actions). Each question snapshots it into `emotion_context`; its `note`
   is added as a system message phrased as what she sees on the call ("unchanged" when the learner's face is the
   same as last time). The UI previews the note live (`emotion_note`) and shows the exact note per answer.
4. **Voice in.** Mic frames (from the microphone the learner chose) → Silero VAD; only utterances (+pre-roll) go to OpenAI; at end of speech the filler plays
   and (if the live transcript has words) a speculative turn starts behind a gate; the final transcript confirms or
   replaces it. See [VOICE.md](VOICE.md) for all turn-taking rules.
4. **Voice out.** The turn streams LLM text to the chat and, through the splitter, to Fish Audio; audio frames are
   forwarded with the turn number only after the gate is open (speculation never speaks early). Barge-in / stop /
   a newer question / reset abort the speaker and send `audio_stop`.
5. **Commit.** A turn is committed to history on `done` (or `interrupted` with the partial text); errors, discarded
   speculation and merged turns commit nothing.

## Concurrency notes

* Everything that mutates a session runs on the event loop; frame analysis and the VAD model factory run in executors.
* One `ChatPlan` is current per session; a newer one cancels the older (`superseded`); the **first** cancel reason
  wins (e.g. `interrupted` keeps the partial answer even if `superseded` follows).
* A speculative plan's voice is held behind `plan.gate`; aborting a speaker that never released audio does **not**
  send `audio_stop` (the filler and the replacement answer share the turn number).
* The live socket has a single writer (queue); audio frames of stopped turns are dropped server-side.

## Failure handling

| Failure | Behaviour |
|---|---|
| Camera denied / missing / busy / unplugged | camera status in the UI, banner "chat and voice still work", expression `unknown` |
| No / several faces, bad light, head turned | `unknown` with a reason, gaps in the timeline, no note in the prompt |
| Vision or expression model missing / MediaPipe broken | vision unavailable in health and socket; chat and voice unaffected (models are imported lazily) |
| Microphone denied / missing | clear message under the composer; typing works |
| Chosen microphone unplugged / unavailable | falls back to the system default (the list shows it); a live switch keeps the conversation |
| Resting face misread (e.g. "angry" while relaxed) | per-person calibration; **Recalibrate**; **Calm** sensitivity; 90 s without a face → learn again |
| Voice detection model missing | `vad_unavailable` → mic off with a message |
| Speech-to-text unreachable / error | `stt_error` toast (rate-limited); a lost final transcript falls back to the live one after 3 s |
| Fish Audio unreachable / error / quota | `tts_error`; the answer still streams as text; a breaker pauses redialling for 30 s |
| She hears herself (speakers) | stricter barge-in bar while audible + browser AEC + echo guard on the transcript |
| Learner pauses mid-sentence | continuation joins the utterances (≤ 3 s, before she answers aloud) |
| WebSocket drop | vision: expression `unknown`; live: spoken turn cancelled; exponential reconnect (0.5 → 5 s) |
| Backend restart | new `boot_id` → the tab clears its view with a toast |
| Missing key / 401 / 404 / 429 / 5xx / network | `error` with code + message; UI error card with Retry (typed) |
| LLM too slow / stalls | first-token 15 s, idle 20 s, total 60 s → `llm_timeout`; client watchdog 25 s |
| Second tab with the same session | newer sockets supersede the older ("Use here" button) |

## Why this shape

One Python process serves the UI, the API and both sockets on one port (fewer moving parts on demo day). Local
models run on the CPU next to the data they need (frames, microphone audio); only text and speech segments leave
the machine, each to the one service that needs it. The reference project (AzIAIBetter) contributed the design
language and the Fish Audio know-how; see EXTERNAL_DEPENDENCIES.md.
