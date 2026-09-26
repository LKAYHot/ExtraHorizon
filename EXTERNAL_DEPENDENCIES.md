# External dependencies, services, models, assets and AI assistance

This file discloses **everything ExtraHorizon uses that was not written for this project**:
runtime services, the ML model, libraries (with versions and licenses), build/test tools,
downloaded assets, design references, research references, and the AI tools used to build it.
Update it in the same change whenever something external is added or removed.

Versions are the ones installed and tested on 2026-09-26 (Windows 11, Python 3.14.7,
Node.js 24.19.0). Direct dependencies are pinned by `backend/uv.lock` and
`frontend/package-lock.json`.

---

## 1. Summary

| What | Kind | Runs where | Sees what data |
|---|---|---|---|
| **OpenAI API** — `gpt-6-luna` (fallback `gpt-5.5`) | LLM service (the only one) | OpenAI cloud | chat text, earlier answers of the session, the adaptation note |
| **Google MediaPipe Face Landmarker** (`face_landmarker.task`, float16 v1) | ML model | locally, CPU | camera frames (in memory only) |
| **Google MediaPipe Tasks usage metrics** | telemetry built into the MediaPipe wheel | Google servers | usage/performance metrics — per Google not images (see §3) |
| Python libraries (FastAPI, uvicorn, pydantic, openai, numpy, mediapipe, OpenCV, …) | code | locally | — |
| JavaScript libraries (Svelte, SvelteKit, Vite, lucide, markdown-it) | code | browser / build | — |
| MediaPipe test portrait image | test asset (downloaded at test time, not committed) | locally | — |
| AzIAIBetter UI (the author's own earlier project) | design reference | — | — |
| Claude Code (Anthropic, model Claude Opus 5.5) | AI coding assistant used to build the project | development only | the repository contents during development |

Nothing else is contacted at runtime: no analytics of our own, no external fonts or CDNs
(system fonts only), no accounts, no cloud storage, no database.

---

## 2. Runtime service: OpenAI (the single LLM integration)

* **API:** Chat Completions with streaming (`POST https://api.openai.com/v1/chat/completions`) via the official `openai` Python SDK; `GET /v1/models/{model}` for the optional deep health check.
* **Model:** `gpt-6-luna` with `reasoning_effort: "none"`, `max_completion_tokens: 700`. Chosen by a benchmark on 2026-09-25 (same prompt, streaming): median time-to-first-token 0.49 s and the best adherence to the adaptation instruction among `gpt-5.5`, `gpt-5.4-nano`, `gpt-4o-mini`, `gpt-4.1-mini`, `gpt-5.4-mini`, `gpt-5.6-luna`. Fallback `gpt-5.5` is used only if the primary model is rejected as unknown (HTTP 404) before streaming. Both are configurable (`EH_LLM_MODEL`, `EH_LLM_FALLBACK_MODEL`).
* **Data sent:** system prompt (tutor style + subject), up to 8 previous exchanges of the session (text only), the new user text; for *Explain differently* one extra system note (no digits, no images, no landmarks, no feelings claimed). Nothing from the camera.
* **Key handling:** `OPENAI_API_KEY` in the repo-root `.env` (git-ignored); read only by the backend; never logged, never returned to the browser (errors are sanitised with a regex that masks `sk-…`). `.githooks/pre-commit` + `pre-push` and `backend/tests/test_secrets.py` block committing keys or `.env` files.
* **Offline alternative:** `EH_LLM_PROVIDER=mock` — a labelled, scripted test double (every answer says "Offline mock tutor — scripted answer, no LLM was called"); used by the automated tests. It is not a second LLM integration.
* Terms: use of the OpenAI API is subject to OpenAI's terms and usage policies.

## 3. ML model and its telemetry: Google MediaPipe

* **Package:** `mediapipe==1.0.1` (Apache-2.0), Tasks API `FaceLandmarker`, VIDEO running mode, CPU (XNNPACK).
* **Model file:** `face_landmarker.task` (float16, version 1, 3,758,596 bytes) from
  `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task`,
  SHA-256 `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` (verified after every download; stored in `backend/models/`, git-ignored). License: Apache-2.0 (Google MediaPipe models; see the model card linked from the MediaPipe Face Landmarker documentation).
* **What it computes for us:** face presence (up to 3 faces), 478 landmarks (used only for the face box), 52 blendshape coefficients and the head transform. We use 6 blendshape averages (brow down, eye squint, mouth press, mouth smile, brow inner up, eye blink) — see docs/CONFUSION_PROXY.md. Frames are decoded, analysed and discarded in memory.
* **Telemetry (important):** the official MediaPipe wheels contain a Google usage-logging client (`ClearcutLoggingClient`, endpoint `https://play.googleapis.com/log`). Google's MediaPipe Tasks privacy notice: *"MediaPipe Tasks APIs send metrics about the performance and utilization of the APIs in your app to Google"*, and processing of input data (images, video, text) happens on device and is not sent. The open-source logger interface records session start/end, frame counts, latency and init errors, plus task name, running mode, OS and Python version. **Our measurement** (Windows, 2026-09-26): with a face landmarker running and no other network activity, the process opened an HTTPS connection to a Google server (172.217.115.4:443) about 60 s into a session and when a session was closed. No documented way to disable it exists (we also tried pointing the uploader at an empty CA bundle: the connection still happened, so we do **not** claim it is blocked). Consequences in ExtraHorizon: the camera starts only after an explicit click on a card that discloses the metrics; the server does not create a MediaPipe session at start-up; the privacy card, README and pitch say so. Google states that apps using MediaPipe are responsible for obtaining users' informed consent for these metrics.

## 4. Python packages (backend, managed by uv)

Direct dependencies (`backend/pyproject.toml`):

| Package | Version | License | Used for |
|---|---|---|---|
| fastapi | 0.141.1 | MIT | HTTP API, SSE, WebSocket routes |
| uvicorn[standard] | 0.54.0 | BSD-3-Clause | ASGI server (+ httptools, websockets, watchfiles) |
| pydantic | 2.13.5 | MIT | request validation |
| pydantic-settings | 2.15.0 | MIT | configuration from env / `.env` |
| openai | 3.19.2 | Apache-2.0 | OpenAI streaming client |
| numpy | 2.5.3 | BSD-3-Clause (+ bundled licenses) | frame buffers |
| mediapipe | 1.0.1 | Apache-2.0 | Face Landmarker (see §3) |
| pytest *(dev)* | 9.1.1 | MIT | tests |
| pytest-asyncio *(dev)* | 1.4.0 | Apache-2.0 | async tests |
| httpx *(dev)* | 0.28.1 | BSD-3-Clause | test client, `demo_check.py` |

Notable transitive packages: starlette 1.7.0 (BSD-3-Clause), anyio 4.15.1 (MIT),
websockets 17.1 (BSD-3-Clause, also used by `demo_check.py`), opencv-contrib-python 5.0.0.93
(Apache-2.0; JPEG decode, colour conversion, test tooling — pulled in by mediapipe),
absl-py 2.5.0, flatbuffers 25.12.19, certifi (MediaPipe's CA bundle), matplotlib 3.11.2
(PSF-based license) and sounddevice 0.5.6 (MIT) — the last two are required by the mediapipe
wheel but not used by ExtraHorizon. Build backend: hatchling (MIT).

## 5. JavaScript packages (frontend, npm)

| Package | Version | License | Used for |
|---|---|---|---|
| svelte | 5.57.1 | MIT | UI framework (runes) |
| @sveltejs/kit | 2.70.3 | MIT | app framework (SPA, prerendered shell) |
| @sveltejs/adapter-static | 3.0.10 | MIT | static build served by FastAPI |
| @sveltejs/vite-plugin-svelte | 7.3.1 | MIT | build |
| vite | 8.3.1 | MIT | dev server (proxy) and bundler |
| @lucide/svelte | 1.48.0 | ISC | icons (only the ~35 imported ones are bundled) |
| markdown-it | 15.0.2 | MIT | rendering tutor answers (`html: false` → model HTML is escaped) |
| vitest *(dev)* | 5.0.2 | MIT | unit tests |
| svelte-check *(dev)* | 4.7.6 | MIT | type/a11y checks |
| @playwright/test *(dev)* | 1.63.0 | Apache-2.0 | browser e2e tests (drives the installed Microsoft Edge; no browser download) |

Known advisory: `npm audit` reports a low-severity issue in `cookie <0.7.0` via
`@sveltejs/kit` (server-side cookie parsing). ExtraHorizon ships a static build
(`ssr = false`, served by FastAPI), so SvelteKit's server runtime never runs in the demo.

## 6. Toolchain

Python 3.14.7 (CPython, managed by uv) · uv 0.12.5 · Node.js 24.19.0 / npm 11.17.0 ·
Git 2.55 · Microsoft Edge (for Playwright) · PowerShell / Git Bash (scripts).
Chromium flags used only in tests: `--use-fake-ui-for-media-stream`,
`--use-fake-device-for-media-stream`, `--use-file-for-fake-video-capture`.

## 7. Downloaded assets used only for testing

* **MediaPipe test portrait** — `https://storage.googleapis.com/mediapipe-assets/portrait.jpg` (part of MediaPipe's public test assets). Downloaded at test time into `backend/tests/.cache/` (git-ignored), used by the vision tests and to build a looping `.y4m` "virtual camera" clip (`backend/scripts/make_fake_camera.py` → `frontend/e2e/.cache/`, git-ignored) so the e2e tests exercise the real camera path without anyone's face. Not redistributed.

## 8. Design and code references

* **AzIAIBetter UI** (`F:\TinyTools2\AzIAIBetter\ui\web`, the project author's own earlier Svelte 5 + Go console) — the design language was adapted and re-coloured to navy/blue/violet: the "one material" plane/raise/well tokens with sheen and depth levels, grain + dot-grid background, cursor spotlight on cards, the focus "beam" around the composer, chrome text for the logo, motion rules (transform/opacity only, paused in background tabs and for reduced motion), and the Vite proxy keep-alive agent (a fix for intermittent ECONNRESET on Windows). Its Go server was not used (spec §3 keeps a Go service out of the critical path; FastAPI serves the UI).
* **Chart colours and chart rules** — the timeline uses the first three slots of the reference data-visualisation palette from Claude Code's bundled *dataviz* skill (`#3987e5`, `#d95926`, `#199e70`), validated with that skill's palette validator against the navy chart surface `#0e1629` (all checks pass, all pairs), plus its mark/interaction rules (2 px line, hairline grid, threshold dashed, hover crosshair, table view).
* **Icons** — Lucide (ISC). **Fonts** — system fonts only.

## 9. Research references (for the confusion-proxy heuristic)

* B. T. McDaniel, S. K. D'Mello, B. G. King, P. Chipman, K. Tapp, A. C. Graesser (2007). *Facial features for affective state detection in learning environments.* Proc. CogSci 2007.
* J. F. Grafsgaard, K. E. Boyer, J. C. Lester (2011). *Predicting facial indicators of confusion with hidden Markov models.* Proc. ACII 2011.
* S. D'Mello, A. Graesser — research on confusion during learning (overview used for the framing "confusion is associated with brow lowering (AU4) and lid tightening (AU7)").
* Google, *MediaPipe Face Landmarker* documentation and *MediaPipe Tasks privacy notice* (developers.google.com/edge/mediapipe).

These papers motivate which cues we look at; no data or code from them is used, and the
heuristic's weights were not fitted to any dataset.

## 10. AI assistance used to build ExtraHorizon

* **Claude Code** (Anthropic's agentic coding tool, desktop app) running **Claude Opus 5.5** (`claude-opus-5-5`) designed and wrote the backend, frontend, tests, scripts, documentation and the project skills in `.claude/skills/`, following the team's implementation brief (`ExtraHorizon_ShellHacks_Implementation_Prompt.md`). It ran the tests, the OpenAI model benchmark, the browser checks and the MediaPipe network measurements reported here.
* A separate Claude sub-agent performed an independent read-only code review; confirmed findings were fixed and re-tested.
* Claude Code skills used during development: *dataviz* (chart palette + validator), *skill-creator* (format of the project skills).
* At runtime the tutor's answers are generated by OpenAI (§2); no Anthropic model is called by the app.
* The human team (repository owner) provided the brief, the design reference project and the OpenAI API key, and is responsible for the live camera rehearsal (docs/TEST_MATRIX.md lists what was and was not tested by the agent).
