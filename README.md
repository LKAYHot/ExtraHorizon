# ExtraHorizon — Rika, an emotion-aware voice tutor you can actually talk to

ExtraHorizon is an AI tutor you **talk to** — hands-free, like a call. **Rika** (a tsundere
anime girl with an expert's rigour) answers **out loud** in an expressive Fish Audio voice,
fills the thinking gap with a natural "Hmm…", stops the moment you talk over her, and lets you
pause mid-sentence without cutting you off. A **local** camera pipeline first learns **your** relaxed
face (a 2.5 s calibration), then estimates your **facial expression** relative to it (8 emotions +
valence/arousal), visualises it live, and gives her a short, words-only
description — her "eyes" on the call — so she adapts her tone and pacing like a person would.

> Key chain: **mic → local voice detection → live transcript → LLM (+ expression note) → voice cues → Fish voice → you**,
> and **camera → on-device face + expression models → per-person calibration → emotion engine → prompt note**.
> Expressions are estimates of how a face *looks* — not a reading of anyone's feelings.

Built for ShellHacks. Stack: **SvelteKit (Svelte 5) → Python FastAPI → OpenAI (chat + realtime
transcription) + Fish Audio (drama-3-preview)**, with **MediaPipe**, **EmotiEffLib** and **Silero
VAD** running on the local CPU.

---

## Quick start (Windows, 3 commands)

Prerequisites: [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`), Node.js ≥ 22.12 — tested with 24
(`winget install OpenJS.NodeJS.LTS`), a webcam and a microphone (both optional; headphones recommended), an
OpenAI API key and a Fish Audio API key.

```powershell
.\scripts\setup.ps1          # backend deps, 3 local models (+ SHA-256 check), UI build, .env from template
notepad .env                 # OPENAI_API_KEY=...  FISH_API_KEY=...  (.env is git-ignored and blocked by the hooks)
.\scripts\start.ps1 -Open    # http://127.0.0.1:8765
```

macOS / Linux / Git Bash: `./scripts/setup.sh`, then `./scripts/start.sh --open`.

Variants: `-MockLLM` (labelled offline scripted tutor) · `-MockVoice` (offline voice doubles: a tone
instead of Fish Audio, a scripted transcript) · `-Dev` (Vite hot reload on http://127.0.0.1:5173) ·
`uv run extrahorizon --help` in `backend/`.

## Remote demo: the PC at home, the laptop anywhere

The laptop only needs a browser: the PC runs everything heavy and is reached through **Cloudflare
Tunnel**, protected by an access key.

```powershell
.\scripts\demo-host.ps1 -PublicUrl https://demo.example.com   # once: remembers the URL, creates the access key
.\scripts\demo-host.ps1 -ShowKey                               # the key to type on the laptop
.\scripts\demo-host.ps1 -Check                                 # server, tunnel, public URL, key, sleep settings
.\scripts\demo-host.ps1 -Install                               # optional: start it automatically at logon
```

The tunnel's public hostname must point to `http://127.0.0.1:8080`. Setup, security model, privacy
differences (Cloudflare relays the camera and microphone traffic) and troubleshooting:
[docs/REMOTE_DEMO.md](docs/REMOTE_DEMO.md).

## The 60–90 s demo

1. Open the app → **Turn on camera** (the card explains the data path) → look at the screen with a relaxed
   face for ~3 s (**Calibrating…**, dashed violet box) → the face box gets a label (*Neutral*); the
   **Expression** panel shows the dominant expression, 8 calibrated bars, the mood map and the stacked
   timeline; **What Rika is told** shows the exact note. **Calm · Balanced · Expressive** sets how readily an
   expression is reported; **Recalibrate** learns your face again.
2. Click the **microphone** → read the one-time disclosure → pick the microphone in its list (also in the sidebar
   and under the chat while talking; the choice is remembered) → **Turn on microphone**. Ask *"Can you see me?"* — she says she
   does and what you look like (briefly, in character). Just talk:
   *"Explain recursion to me."* The orb turns green while she hears you; a filler ("Hmph.") plays the
   instant you stop; her answer starts ≈1.7–2.5 s after you stop speaking, in character, with voice cues
   shown as small stage directions in the chat.
3. Talk over her — *"Wait, stop."* — she stops at once (and "wait, stop" alone does not start a new answer).
4. Pause mid-sentence ("Explain recursion to me… and give an example") — the parts are joined into one question.
5. Smile or frown clearly for a second → the expression changes in the panel (a small brow twitch or a lowered
   head does not); the next answer's **expression sent** chip shows what went into her prompt.
6. **New session** clears chat, emotion history and timeline.

No camera? Everything still works; the **Demo simulation mode** card drives the same emotion engine with a
chosen expression — labelled **SIMULATED** everywhere. Full script, fallbacks and honest claims:
[docs/PITCH.md](docs/PITCH.md).

## Architecture

```
Browser (SvelteKit SPA)                       Python process, same machine (FastAPI)                   Cloud
camera → 480px JPEG ─WS /api/vision─▶ MediaPipe face → quality gates → EmotiEffLib (ONNX, upright square crop + mirror)
                  ◀── tick / emotion_note ──  → calibration (baseline · facial actions · pose) → engine ─┐
mic → AudioWorklet PCM16 24 kHz ─WS /api/live─▶ Silero VAD → speech only ──────────────────────────┼─▶ OpenAI gpt-live-transcribe
                  ◀── vad / stt / heard ────   turn logic: filler · speculation · barge-in ·     │
                  ◀── turn meta/delta/done ─   "wait, stop" · continued sentences · echo guard     │
                  ◀── PCM voice (turn-tagged)  context (persona + expression note + rules) ───────┼─▶ OpenAI gpt-6-luna (stream)
typed chat ─POST /api/chat (SSE)──────────▶   splitter → voice cues kept, code/maths removed ─────┴─▶ Fish Audio drama-3-preview
```

* Contract (every message and field): [docs/CONTRACT.md](docs/CONTRACT.md)
* Components, turn-taking, failure handling: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
* Voice pipeline and measured latencies: [docs/VOICE.md](docs/VOICE.md)
* Emotion method, prompt note, **limitations**: [docs/EMOTIONS.md](docs/EMOTIONS.md)
* What was tested and how: [docs/TEST_MATRIX.md](docs/TEST_MATRIX.md)
* Everything external (services, models, libraries, assets, AI assistance): [EXTERNAL_DEPENDENCIES.md](EXTERNAL_DEPENDENCIES.md)

| Path | What |
|---|---|
| `backend/extrahorizon/live_ws.py` · `turns.py` | the voice conversation (turn-taking) · one tutor turn (LLM → splitter → voice) |
| `backend/extrahorizon/voice/` | Fish Audio client, fillers, speech-to-text, Silero VAD segmenter, cue handling, splitter, silence cap |
| `backend/extrahorizon/emotion/` · `vision/` | expression model, per-person calibration, emotion engine · MediaPipe analysis, quality gates, model download |
| `backend/extrahorizon/context.py` | what the LLM receives: the Rika persona, voice-cue rules, the expression note |
| `backend/extrahorizon/sessions.py` · `app.py` · `vision_ws.py` | sessions/turns/reset · HTTP/SSE/routes · camera socket |
| `frontend/src/lib/` | app store, voice controller + audio (mic worklet with device choice, player), camera controller, components |
| `backend/scripts/` | `demo_check.py` (live chain against the running app), `vision_probe.py` (webcam check), `make_fake_camera.py` / `make_fake_mic.py` (test clips) |
| `.claude/skills/` | Claude Code skills for running, testing, rehearsing, tuning and the architecture contract |

## Privacy — what goes where (the same text is in the app)

* **Camera frames** are downsized in the browser and sent over a **localhost** WebSocket to the ExtraHorizon
  Python process on the same computer, analysed in memory (MediaPipe + the on-device expression model) and
  discarded — never written to disk, never sent to any cloud service.
* **Microphone audio** goes to the same local process, where Silero VAD detects speech; **only the parts where
  you speak** (+0.4 s before) are sent to **OpenAI** for transcription. Nothing is recorded.
* **OpenAI (chat)** receives your messages (typed or transcribed), her earlier answers in this session and — only
  when one face is clearly in view and calibrated — a short words-only description of your apparent expression and
  visible facial actions (e.g. "frowning"). No images, no numbers.
* **Fish Audio** receives the text of her answers (and nine filler phrases once) to speak them.
* **Google (MediaPipe library):** the official MediaPipe wheels send **usage metrics** (e.g. frame counts,
  latency, OS/Python version) to Google while a camera session runs — per
  [Google's notice](https://developers.google.com/edge/mediapipe/solutions/tasks#mediapipe_tasks_privacy_notice)
  never images or video. The camera starts only after an explicit click on a card that says so.
* **Stored:** nothing. Sessions live in memory; *New session* or stopping the backend deletes them.
* The API keys live only in the git-ignored `.env`, read by the backend; never sent to the browser or logged.
* **Remote demo (Cloudflare Tunnel):** camera frames and microphone audio travel from the laptop over HTTPS to
  **Cloudflare**, which decrypts and re-encrypts them into the tunnel to the presenter's PC — analysed there in
  memory as above; the app then shows this wording instead of "stays on this computer", and asks for an access key.

## Tests

```powershell
.\scripts\test.ps1 -E2E      # pytest + vitest + svelte-check + build + Playwright (virtual camera AND virtual microphone)
cd backend; uv run python scripts/demo_check.py --runs 3 --speech ..\frontend\e2e\.cache\question.wav   # live, real providers
cd backend; uv run python scripts/demo_check.py --base https://demo.example.com --access-key-env           # … through the tunnel
```

Results and the manual matrix (pass / fail / not tested): [docs/TEST_MATRIX.md](docs/TEST_MATRIX.md).

## Configuration

Every threshold and timing is an environment variable (`EH_*`) with defaults in
`backend/extrahorizon/config.py`; the annotated list is in [.env.example](.env.example) — e.g.
`EH_VAD_END_SILENCE_MS` (how fast she answers), `EH_BARGE_IN_*` (how easily you interrupt her),
`EH_VOICE_MERGE_WINDOW_S`, `EH_EMOTION_SENSITIVITY` / `EH_EMOTION_CALIBRATION_S` / other `EH_EMOTION_*`, `EH_FISH_*`,
and for the remote demo `EH_PUBLIC_URL`, `EH_ACCESS_KEY`, `EH_REMOTE_MAX_FPS`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "OPENAI_API_KEY is not set" / no voice (`FISH_API_KEY missing`) | put the keys in `.env` (repo root) and restart |
| She interrupts herself / stops when she hears her own voice | use headphones or lower the speaker volume; raise `EH_BARGE_IN_THRESHOLD` / `EH_BARGE_IN_MIN_MS` |
| She answers before you finished | raise `EH_VAD_END_SILENCE_MS` (e.g. 700); pauses up to `EH_VOICE_MERGE_WINDOW_S` are already joined |
| Microphone error | allow the microphone in the address bar; only `localhost`/HTTPS pages may use it |
| Wrong microphone (e.g. the webcam mic) | choose it in the **Microphone** list (sidebar, or under the chat while talking) — it switches live; an unplugged device falls back to the default |
| "Vision unavailable" | camera permission / another app using the camera / model download failed (`uv run python -m extrahorizon.vision.model_fetch`) — chat and voice keep working |
| Expression stays *Unknown* | one face, well lit, facing the screen, not too far away |
| Reads *Angry* / *Unimpressed* while you are relaxed | **Recalibrate** with a relaxed face (it learns *your* neutral); **Calm** needs clearer expressions |
| A clear expression stays *Neutral* | was the face relaxed during calibration? **Recalibrate**; **Expressive** reacts to subtler expressions |
| Stuck on *Calibrating…* | look at the screen with a relaxed face and stay quiet ~3 s (talking and a turned head are skipped) |
| Port 8765 busy | an old backend is still running — stop it (`Get-NetTCPConnection -LocalPort 8765`) |
| "UI is not built yet" page | `cd frontend && npm run build`, restart the backend |

## License

MIT — see [LICENSE](LICENSE). Third-party components keep their own licenses (see EXTERNAL_DEPENDENCIES.md).
