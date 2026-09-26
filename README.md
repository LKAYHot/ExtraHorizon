# ExtraHorizon — an adaptive AI tutor that notices when an explanation isn't landing

ExtraHorizon streams tutor answers from an LLM while a **local** vision pipeline estimates a
*confusion proxy* from your facial expression. When that estimate stays high for about two
seconds after an answer, the tutor offers **"Explain differently"** — and re-explains with an
analogy, a concrete example and short steps. A **"Why it adapted"** card shows the real signal,
the rule that fired, the strategy and the exact note sent to the model.

> Key chain: **camera → local signal → stable event → context → visibly different LLM answer.**
> This is an experimental estimate of visible behavioural cues, not a reading of anyone's inner state.

Built for ShellHacks. Stack: **SvelteKit (Svelte 5) → Python FastAPI → OpenAI**, with Google
**MediaPipe Face Landmarker** running on the local CPU.

---

## Quick start (Windows, 3 commands)

Prerequisites: [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`), Node.js ≥ 22.12 — tested with 24 (`winget install OpenJS.NodeJS.LTS`), a webcam (optional), an OpenAI API key.

```powershell
.\scripts\setup.ps1          # backend deps, face model download (+ SHA-256 check), UI build, .env from template
notepad .env                 # set OPENAI_API_KEY=...   (.env is git-ignored and blocked by pre-commit/pre-push hooks)
.\scripts\start.ps1 -Open    # http://127.0.0.1:8765
```

macOS / Linux / Git Bash: `./scripts/setup.sh`, then `./scripts/start.sh --open`.

Variants: `start.ps1 -MockLLM` (labelled offline scripted tutor — no key, no internet) ·
`start.ps1 -Dev` (Vite hot reload on http://127.0.0.1:5173) · `uv run extrahorizon --help` in `backend/`.

Manual equivalent: `cd backend && uv sync && uv run python -m extrahorizon.vision.model_fetch`,
`cd frontend && npm install && npm run build`, then `cd backend && uv run extrahorizon`.

## The 60–90 s demo

1. Open the app → click **Turn on camera** (first visit only; the card explains the data path) → allow the browser prompt. The face box appears and a neutral baseline is captured for 2.5 s.
2. Ask **"Explain recursion to me."** → the answer streams (≈0.6 s to first token in our tests).
3. Frown for ~2 s → the meter crosses 0.65, the hold bar fills, **Possible confusion detected**.
4. Click **Explain differently** → a different explanation (analogy → example → short steps), badged *Adapted*.
5. **Why it adapted** shows the measured values, the rule, the strategy, the exact note — and *"decrease observed"* only if the estimate really went down afterwards.
6. **New session / Reset demo** clears chat, signal state, cooldown and timeline.

No camera? The UI says "Vision unavailable — chat still works". The **Demo simulation mode** card
drives the same engine with a slider; everything it produces is labelled **SIMULATED**.
Full script, fallbacks and honest claims: [docs/PITCH.md](docs/PITCH.md).

## Architecture

```
Browser (SvelteKit SPA)                  Python process, same machine (FastAPI)                     OpenAI
camera → 480px JPEG ──WS /api/vision──▶ MediaPipe (thread pool) → quality gates → confusion proxy
tick/event/marker ◀────────────────────  → per-session state engine (EMA · 2 s hold · 15 s cooldown)
chat ──POST /api/chat (SSE)───────────▶ session → context builder ──(text + abstract note)──▶ gpt-6-luna
     ◀── meta / delta / done / error ──  timeouts · cancel · commit only on success
```

* Contract (every message and field): [docs/CONTRACT.md](docs/CONTRACT.md)
* Components, failure handling, data flow: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
* Confusion proxy method, parameters, **limitations**: [docs/CONFUSION_PROXY.md](docs/CONFUSION_PROXY.md)
* What was tested and how: [docs/TEST_MATRIX.md](docs/TEST_MATRIX.md)
* Everything external (libraries, model, APIs, assets, AI assistance): [EXTERNAL_DEPENDENCIES.md](EXTERNAL_DEPENDENCIES.md)

| Path | What |
|---|---|
| `backend/extrahorizon/engine.py` | the adaptation rule (pure, clock-injected) |
| `backend/extrahorizon/vision/` | MediaPipe analysis, quality gates, confusion proxy, model download |
| `backend/extrahorizon/context.py` | what the LLM receives (strategies + adaptation note) |
| `backend/extrahorizon/llm.py` | OpenAI streaming, error mapping, labelled mock |
| `backend/extrahorizon/sessions.py` · `app.py` · `vision_ws.py` | sessions/events/reset · HTTP/SSE · camera socket |
| `frontend/src/lib/` | app store, camera/socket controller, SSE client, components |
| `backend/scripts/` | `demo_check.py` (live chain ×N), `vision_probe.py` (webcam tuning), `make_fake_camera.py` |
| `.claude/skills/` | Claude Code skills for running, testing, rehearsing, tuning and the architecture contract |

## Privacy — what goes where (the same text is in the app)

* **Camera frames** are downsized in the browser and sent over a **localhost** WebSocket to the ExtraHorizon Python process on the same computer, analysed in memory by Google's MediaPipe library and discarded. They are never written to disk and never sent to OpenAI. (If you run the backend on another machine, frames travel over the network — the UI then drops the "stays on this device" claim.)
* **OpenAI** receives: your chat messages, the tutor's earlier answers in this session and — only after you click *Explain differently* — a one-sentence adaptation note (no numbers, no images, no landmarks).
* **Google (MediaPipe library):** the official MediaPipe wheels send **usage metrics** (performance/utilisation: e.g. task name, frame counts, latency, OS/Python version) to Google — we observed HTTPS connections to a Google server about a minute into a camera session and when a session ended. Per [Google's MediaPipe privacy notice](https://developers.google.com/edge/mediapipe/solutions/tasks#mediapipe_tasks_privacy_notice), input images/video are not sent. There is no documented switch to turn this off; ExtraHorizon therefore starts the camera only after an explicit click on a card that discloses it, and does not create a MediaPipe session at server start.
* **Stored:** nothing. Sessions live in memory; *Reset demo* or stopping the backend deletes them.
* The API key lives only in the git-ignored `.env`, read by the backend; it is never sent to the browser or logged.

## Tests

```powershell
.\scripts\test.ps1 -E2E      # pytest (72) + vitest (16) + svelte-check + build + Playwright (9)
cd backend; uv run python scripts/demo_check.py --runs 10    # live chain against the running app + real OpenAI
```

Results and the manual matrix (pass / fail / not tested): [docs/TEST_MATRIX.md](docs/TEST_MATRIX.md).

## Configuration

All thresholds and timings are environment variables (`EH_*`) with defaults in
`backend/extrahorizon/config.py`; the annotated list is in [.env.example](.env.example).
The engine defaults follow the spec's working hypotheses (α 0.2, threshold 0.65, 2 s hold,
15 s cooldown) and should be re-checked with the real camera before the show
(`backend/scripts/vision_probe.py`, see docs/CONFUSION_PROXY.md).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Chat: "OPENAI_API_KEY is not set" | put the key in `.env` (repo root) and restart |
| "Vision unavailable" | camera permission / another app using the camera / model download failed (`uv run python -m extrahorizon.vision.model_fetch`) — chat keeps working |
| Face not detected | light the face, move closer, one person in frame, **Recalibrate** |
| Port 8765 busy | an old backend is still running — stop it (`Get-NetTCPConnection -LocalPort 8765`) |
| "UI is not built yet" page | `cd frontend && npm run build`, restart the backend |

## License

MIT — see [LICENSE](LICENSE). Third-party components keep their own licenses (see EXTERNAL_DEPENDENCIES.md).
