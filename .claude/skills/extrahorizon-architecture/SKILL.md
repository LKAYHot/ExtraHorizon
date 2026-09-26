---
name: extrahorizon-architecture
description: Architecture map, API/WebSocket contract and non-negotiable invariants of ExtraHorizon (SvelteKit UI ⇄ FastAPI ⇄ OpenAI chat + realtime transcription ⇄ Fish Audio voice; local MediaPipe + expression model + Silero VAD; per-session calibration + emotion engine and voice turn logic). Use this BEFORE changing any message, endpoint, socket event, turn-taking rule, calibration or emotion-engine rule, prompt/persona/context text (what Rika "sees", how she talks), privacy wording or dependency — and whenever you need to know "where does X live", "what does the UI receive", "what is sent to OpenAI / Fish Audio", or when adding a feature (new voice rule, new emotion view, new provider). Also use it when updating EXTERNAL_DEPENDENCIES.md, README or the pitch. For the utility-coordination analysis (coord/, the map panel) also load extrahorizon-coord-analysis.
---

# ExtraHorizon architecture & contract

```
Browser (SvelteKit SPA)                              Python process on the same machine (FastAPI)                     Cloud
camera → 480px JPEG ──WS /api/vision──► VisionConnection → FaceAnalyzer (MediaPipe + EmotiEffLib ONNX, upright square crop + mirror)
  tick / calibration / emotion_note ◄─── → quality gates → Session.calib (Calibrator) → Session.emotion (EmotionEngine) → note
  calibrate / sensitivity ──────────────►
mic (chosen device) → AudioWorklet PCM16 24 kHz ─WS /api/live─► LiveConnection → VadSegmenter (Silero) → OpenAIRealtimeStt ─────► gpt-live-transcribe
  vad / stt / heard / turn / audio ◄──── turn logic (filler, speculation, barge-in, stop, merge, echo)
                                          → TurnRunner → LLM stream ──────────────────────────────────────────► gpt-6-luna
                                          → Speaker → TtsSplitter → FishSession ──────────────────────────────► Fish drama-3-preview
typed chat ──POST /api/chat (SSE)──────► same TurnRunner (voice goes to the live socket if open)
analysis turn (question / button) ──────► TurnRunner._run_analysis → CoordService (ArcGIS REST ◄──────────────────── Miami-Dade open data)
  analysis events, map/findings ◄──────── → verify → overlaps → county cross-check → fact sheet → LLM → grounding check
  (browser loads map tiles directly from tile.openstreetmap.org)
```

Source of truth for every message: **`docs/CONTRACT.md`** — change it first, then both sides, then the tests
(`backend/tests/test_api.py`, `test_live.py`, `frontend/src/lib/*.test.js`, `frontend/e2e`). Turn-taking rules:
**`docs/VOICE.md`**. Emotion method and the prompt note: **`docs/EMOTIONS.md`**.

## Where things live

| Concern | File |
|---|---|
| Config / all tunables (env `EH_*`) | `backend/extrahorizon/config.py`, `.env.example` |
| Per-person calibration (baseline, neutral-vs-expression relative to the relaxed face, which expression, hallmark facial actions, pose/talk, sensitivity presets) | `backend/extrahorizon/emotion/calibration.py` (pure, time injected) |
| Emotion engine (weighted EMA, floor, stable dominant, unknown, words-only description) | `backend/extrahorizon/emotion/engine.py` (pure, clock injected) |
| Expression model (ONNX) · face analysis · quality gates · model download | `backend/extrahorizon/emotion/classifier.py` · `vision/analyzer.py` · `vision/quality.py` · `vision/model_fetch.py` |
| Persona "Rika" (a person on a video call; banned assistant phrases), voice-cue rules, webcam note, reply rules | `backend/extrahorizon/context.py` |
| Session state, plans (speculative gate, cancel reasons), commit/abort, reset | `backend/extrahorizon/sessions.py` |
| One turn: LLM → deltas → Speaker (splitter → Fish) → audio frames | `backend/extrahorizon/turns.py` |
| Voice conversation socket, turn-taking | `backend/extrahorizon/live_ws.py` |
| Fish client, fillers, STT, VAD, cues, splitter, silence cap | `backend/extrahorizon/voice/*.py` |
| OpenAI chat streaming, error mapping, fallback model, mock | `backend/extrahorizon/llm.py` |
| HTTP routes, SSE, origin/host guards, static UI | `backend/extrahorizon/app.py` |
| Vision socket (latest-frame-wins, single writer) | `backend/extrahorizon/vision_ws.py` |
| Remote access: transport (local/cloudflare/proxy/network), access key, cookie, brute-force brake, guard | `backend/extrahorizon/access.py` · `/api/access` in `app.py` · `AccessGate.svelte` · `scripts/demo-host.ps1` |
| Utility-coordination analysis: sources, ArcGIS client, verification, overlaps, cross-check, fact sheet + grounding, service, intent | `backend/extrahorizon/coord/*.py` · `/api/coord/*` in `app.py` · `AnalysisPanel.svelte`, `Coord*.svelte`, `coord.js` · docs/ANALYSIS.md · skill `extrahorizon-coord-analysis` |
| Styled select (combobox + listbox, keyboard, portal) | `frontend/src/lib/components/Select.svelte` (used by Subject and the microphone picker) |
| UI state (the only store) · camera + calibration/sensitivity · voice + audio + microphone choice | `frontend/src/lib/app.svelte.js` · `vision.svelte.js` · `voice.svelte.js` + `audio.js` (`MicCapture`) |
| Emotion colours/orders (validated palette) · voice cues in markdown | `frontend/src/lib/emotions.js` · `cues.js` + `markdown.js` |
| Components | `frontend/src/lib/components/*.svelte` |

## Invariants (each is covered by a test — keep them green)

1. **Words only to the LLM**: the note "[What you see on the learner's webcam right now] …" has no digits, no images, no landmarks; it is added only when exactly one face is clearly in view and calibrated (a simulation is labelled as such inside the note too). The persona treats it as her eyes on a video call: says she can see the learner, mentions the face rarely (the note says "Same as when they last spoke" when unchanged), never talks about estimates/readings/cameras/scores, knows a face is not a feeling and believes a correction; without a note she says she can't see them. The UI labels every reading as an *estimate*.
1b. **Calibration first, relative — never erase an expression**: nothing is reported before the learner's baseline exists (status `calibrating`); the relaxed face reads neutral (`p_ref`); *whether* the face shows an expression is measured against the relaxed face, *which* one comes from how the face reads now (classes that gained on neutral). Blendshape hallmarks and pose/talk bonuses only nudge — they never move a clear expression into neutral (that erased a real learner's anger once: docs/EMOTIONS.md). Adaptation happens only while the face is clearly neutral.
1c. **A person, not an assistant**: no service phrases ("How can I help you?", "Tell me what you were asking", "I'll answer directly", "As an AI", …) — listed in `context.py`, asserted in `test_context.py`.
2. **Unknown ≠ neutral**: no/several faces, poor quality, camera off, socket closed, gaps → `unknown`, smoothing restarts, gaps in the timeline, no note. Several faces are never read.
3. **Time, not frames**: smoothing and the dominant-switch hold are wall-clock based.
4. **Per-tab sessions**; no shared state; reset clears history, emotion engine, timeline, stops the voice and cancels a turn.
5. **A turn always ends**: `done` / `interrupted` (partial kept, marked) / `error` / `dropped`; nothing committed on errors, discarded speculation or merged turns; server timeouts + client watchdog.
6. **Speculation never speaks early**: a speculative plan's text and voice stay behind `plan.gate` until the final transcript confirms it; aborting an unreleased speaker sends no `audio_stop` (the filler and the replacement share the turn number).
7. **Barge-in is instant and final**: `audio_stop`/`barge_in` → the browser stops at once; frames of stopped turns are never sent again; first cancel reason wins.
8. **Only speech leaves the machine**: mic audio reaches OpenAI only inside VAD utterances (+pre-roll); camera frames never leave the machine.
9. **Vision or voice failure never disables chat** — heavy libraries load lazily; each provider failure degrades to text with a clear message.
10. **Privacy claims follow the real data path** (loopback check for "stays on this device"; MediaPipe usage metrics disclosed; camera and microphone start only after an explicit consent click).
11. **Simulation is labelled** (SIMULATED / NOT LIVE, striped card, marked spans) and allowed only in that mode / tests.
12. **Secrets**: keys live only in the git-ignored `.env`; hooks in `.githooks/` + `tests/test_secrets.py` block commits/pushes of keys or their values. Never print, log or return a key; check with `len(...)` only.
13. **Remote access** (`access.py`, docs/REMOTE_DEMO.md): the server binds to loopback; "local" = loopback peer **and** no proxy header **and** loopback Host (tunnel requests come from 127.0.0.1 too). Every non-local `/api/*` request and both sockets need the signed access cookie (`POST /api/access` with `EH_ACCESS_KEY`); no key configured → remote refused. The UI shell stays public for the key prompt. Remote privacy wording names Cloudflare; the "stays on this device" claim is local-only.
14. **Analysis facts are verified and grounded** (docs/ANALYSIS.md): every record verified or excluded with a counted reason; she states only the fact sheet (no arithmetic, no contact data) and every analysis answer gets the grounding check; failures and saved copies are said, never guessed; TEST fixtures are labelled everywhere and tests never contact the county; project IDs (never object IDs) identify records across reads.

## When you add or change a dependency, model, dataset, asset, service or AI tool

Update `EXTERNAL_DEPENDENCIES.md` in the same change (name, version, license, what it is used for, what data it
sees). Hackathon rules require disclosing everything external.
