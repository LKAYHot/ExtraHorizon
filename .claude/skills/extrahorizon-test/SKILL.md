---
name: extrahorizon-test
description: Run and extend the ExtraHorizon automated test suites — backend pytest (utility-coordination analysis on synthetic fixtures, per-person calibration, emotion engine, context/persona, voice pipeline with fake providers, live voice socket turn-taking, STT/VAD/Fish clients, API, real MediaPipe + expression model, secret scan), frontend vitest + svelte-check, Playwright e2e with a virtual camera and a virtual microphone, and the live demo_check against the real providers. Use this after ANY code change in backend/ or frontend/, before claiming something works, when a test fails, when adding a feature that needs a test, or when the user asks "проверь", "прогони тесты", "does it still work", "run CI" — even for small edits.
---

# Testing ExtraHorizon

Run the cheapest layer that can catch the bug first, then widen. Everything below runs without the user's
webcam or microphone; only `demo_check` uses the real providers (costs a few cents).

| Layer | Command | Time | Needs |
|---|---|---|---|
| Backend unit + integration | `cd backend && uv run pytest` | ~20 s | nothing (fake LLM, mock TTS/STT, energy VAD) |
| Frontend unit | `cd frontend && npx vitest run` | ~3 s | — |
| Types / a11y / Svelte | `cd frontend && npx svelte-kit sync && npx svelte-check --threshold warning` | ~15 s | — |
| Browser e2e (camera setups + voice) | `cd frontend && npm run e2e` | ~1 min | Edge (default; `PW_CHANNEL=chrome` to switch); Windows SAPI for the virtual mic |
| Live chain, real providers | backend running, then `cd backend && uv run python scripts/demo_check.py --runs 3 --speech ../frontend/e2e/.cache/question.wav` | ~1 min | keys in `.env`, internet |
| Everything | `.\scripts\test.ps1 -E2E` | ~5 min | |

A test that blocks on a WebSocket forever is a bug in the test: use the timeout helpers (`Live.until` in
`test_live.py`, `sync()` ping/pong in `test_api.py`).

## What each suite protects (don't weaken these to make a change pass)

- `test_coord_tools.py` — she knows the whole analysis: finding IDs typed or spoken (EN/RU words), the four tools on all findings, `focus`/`tool`/`recheck` events, a look-up round with grounding over its results, the map following question and answer, the offline tutor using the same tool, OpenAI tool-call deltas from the stream (fake client). FakeLLM mode `tools:[…]` scripts a tool round.
- `test_coord.py` — the utility-coordination analysis on the synthetic TEST fixtures (`fixtures/make_coord_fixtures.py` documents the expected result): every exclusion reason counted per layer, merged multi-part project and record totals, overlap categories, same plan / same project skipped, the county cross-check both ways, the fact sheet (no contact data) + the grounding check catching invented numbers/dates/IDs, EN + RU intent, an analysis turn over SSE (progress → ready → grounded answer → follow-up in context), REST catalog/analyze/report/recheck, failures said plainly, a saved copy used and labelled, unreadable layers named (not "empty"), failed reads retried, republished layers (new object IDs) change nothing, a cut report says so, only the spoken summary is voiced; strict intent (tutoring questions never start it; an open analysis only answers questions about it), rules validated and kept only when they worked, every pair and highlight listed, a stopped analysis says so, grounding with units / written dates / percentages / name numbers, finished vs stopped statuses, county pairs counted once, inclusive days, the county's boundary polygon (and its labelled fallback), the analysis turned off. Tests never contact the county (`make_settings` sets `coord_offline_dir`).
- `test_calibration.py` — modelled on a real learner's measured frames: calibration takes ~2.5 s; a stern resting face (raw anger > 0.9) reads neutral; that face snarling reads **angry, not disgusted**; lips pressed together read angry (disgust needs a raised lip / wrinkled nose); a stern face that smiles is happy; small shifts stay neutral; a neutral resting face keeps the classifier's judgement; anger shows without blendshape help; a lowered head and talking need a clearer face; talking frames are skipped (8 s fallback); adaptation never absorbs a smile; presets are ordered; restart / sensitivity; hallmarks and action words fit the expression.
- `test_emotion.py` — time-based smoothing (30 vs 5 fps agree), dominant switches only after hold + margin, close competitors don't flicker, unknown/gaps restart smoothing (never "neutral"), source switch, words-only description (no digits) naming the previous expression, stale state not described, reset.
- `test_vision.py` — quality gates → `unknown` with a reason; the real expression model on the portrait (8 probs sum to 1, valence/arousal in range); real MediaPipe + model: one face → estimate, two faces → no estimate, dark → unknown, garbage → bad_frame.
- `test_context.py` — persona (tsundere + expert, English, Fish cue rules, short spoken replies, a person on a video call who sees the learner through the webcam note, banned assistant phrases, a face is not a feeling), the webcam note wording (simulation labelled, "unchanged"), note layout (stable prefix, emotion note, reply rules, voice note), only text reaches the model, interrupted answers marked, history limit.
- `test_voice.py` — cue parsing/stripping, `speakable` (cues kept, markdown/code/URLs/stray brackets removed, LaTeX → words), splitter (early first chunk, never inside a cue, cue carry-over, bursts), SilenceCap, fillers (cached, no repeats, mood), Fish protocol against a fake server (start/text/flush/stop, audio, error, silence trim), dial headers + warm pool, breaker.
- `test_stt.py` / `test_vad.py` — realtime transcription session config, partial/final mapping per utterance, context-bias prompt updates; VAD segmentation (pre-roll, clicks ignored, comma pauses kept, strict barge-in bar, max length, reset), Silero on silence/noise.
- `test_live.py` — the voice socket end to end: filler + answer voice on the **same turn** after a speculation mismatch (regression), speculation confirmed → one LLM call, barge-in stops voice and keeps the partial answer, "wait, stop" only stops, a paused sentence is joined, echo ignored without an LLM call, stop button, text-only mode, mic off, typed question spoken on the socket, REST interrupt, stop-command and join helpers, a spoken utility-coordination question (analysis events on the socket, fact sheet, grounding).
- `test_api.py` — health, SSE stream/commit, errors/timeouts/retry, missing key, supersede, simulated expression → note → prompt → stored context, sim off → unknown, real frames through the socket (calibration → neutral), recalibrate + sensitivity over the vision socket, socket close → unknown, reset, isolation, supersede, cross-origin HTTP + WebSockets, host guard, broken OpenCV never breaks chat.
- `test_secrets.py` — no key patterns and no value of any secret in the local `.env` in anything git would commit; `.env` ignored.
- `test_remote.py` — transport detection (a tunnel's 127.0.0.1 requests are remote), remote refused without a key, the key gate + cookie flags (HttpOnly, Secure, SameSite=Strict, no key inside), local never needs it, the UI shell stays public, tampered/expired/rotated cookies, brute-force brake (per client + overall), remote WebSockets (transport, 8 fps profile, 4401 without cookie), same-origin login, public URL validation.
- `frontend/src/lib/*.test.js` — coordination helpers (`coord.test.js`: distances, timing, pair filter in either order, utility-first order, year ticks), markdown XSS/remote images + cue rendering, cue helpers, emotion palette/orders (documented colours, validated stack order), audio frame parsing + gapless player (turn cut, stop, stopAll), voice controller protocol (captions incl. continued sentences, playback reporting, barge-in, mute, microphone list / choice / fallback), camera controller races + recalibrate / sensitivity (sent on every connect), formatting.
- `frontend/e2e/analysis.spec.js` — the analysis on the TEST fixtures with map tiles blocked: question → card → map/findings/county marks/live re-check/pair picker/schedules/sources/stricter rule → grounded answer → follow-up without a new run → privacy line → reset; started from the panel and by a Russian question. Needs a fresh `npm run build`.
- `frontend/e2e/*.spec.js` — demo scenario with the real models on a virtual camera (calibration → "tracking (calibrated to you)" → Neutral, Recalibrate, expression, face label, prompt note, cue chips, per-answer note, table view, labelled simulation, reset), consent remembered, refresh restore, duplicated tab, two faces / no face / camera off / camera + microphone denied, **voice**: virtual microphone → hearing → spoken question → answer → speaking → Stop, and **remote** (a browser sending Cloudflare's headers): the access-key gate → wrong key → right key → the app, tunnel wording, camera at ≤ 8 fps, chat, remembered after a reload.
- Through the REAL tunnel (manual, real providers): `scripts/demo_check.py --base <public URL> --access-key-env [--resolve host:ip]`.

## Writing new tests

- Test observable behaviour and failure paths. Inject time in engine tests; never `sleep` for engine timing.
- Use `conftest.make_settings(...)` (mock providers, short timeouts, the coord fixtures), `FakeLLM(script=[...])` modes `ok|error|hang|stall|fail_mid|slow|length`, `EnergyVad` + `speech_pcm()/silence_pcm()` for voice, `voice_app()` / `open_live()` in `test_live.py`. Tests never read `.env` (`_isolate_env`).
- Fake keys in tests must not look like real ones (no `sk-…`) — the secret scan will (correctly) flag them.
- Real-image/model tests use the `portrait_jpeg`, `model_path`, `emotion_model_path`, `vad_model_path` fixtures (downloaded once, skipped offline).
- A controlled expression is allowed only in tests or the labelled *Demo simulation mode*.

## When something fails

1. Read the assertion; for e2e open `frontend/test-results/*/error-context.md`.
2. Reproduce with the smallest layer (`pytest -k …`, `npx playwright test -g "<title>" --project voice`).
3. Fix the code, rerun the layer and the layers above it. Report results honestly — skipped/not-run checks are reported as such.
