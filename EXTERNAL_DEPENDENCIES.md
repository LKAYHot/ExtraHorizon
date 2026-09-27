# External dependencies, services, models, assets and AI assistance

This file discloses **everything ExtraHorizon uses that was not written for this project**:
runtime services, ML models, libraries (with versions and licenses), build/test tools,
downloaded or generated assets, design and code references, research references, and the AI
tools used to build it. Update it in the same change whenever something external is added or removed.

Versions are the ones installed and tested on 2026-09-26 (Windows 11, Python 3.14.7,
Node.js 24.19.0). Direct dependencies are pinned by `backend/uv.lock` and
`frontend/package-lock.json`.

---

## 1. Summary

| What | Kind | Runs where | Sees what data |
|---|---|---|---|
| **OpenAI Chat Completions** — `gpt-6-luna` (fallback `gpt-5.5`) | LLM service | OpenAI cloud | chat text (typed or transcribed), earlier answers of the session, a words-only note about the learner's apparent facial expression and visible facial actions; in analysis turns the fact sheet of the utility-coordination analysis (public county records, no contact data); in hub turns the hub's fact sheet — public Q&A excerpts with their authors' display names, package facts, the board's matching entries (names, skills, interests, ideas, availability, team size as their owners wrote them — never the contact line) and, for teammates and mentors, the public people found: a GitHub profile's login, public name, city, what its public repositories use, last push, "available for hire" and a few words from the bio ("student", "hackathons" — never the bio, e-mail, links or company); a Stack Overflow top answerer's display name, tag, answer count, score and reputation |
| **OpenAI Realtime transcription** — `gpt-live-transcribe` | speech-to-text service | OpenAI cloud | only the **speech segments** of the microphone audio (detected locally), PCM 24 kHz |
| **Fish Audio live TTS** — model `drama-3-preview`, voice `c5d8a284092847df9e3c7308aeedc5f2` | text-to-speech service | Fish Audio cloud | the text of the tutor's answers (with voice cues) and the short filler phrases |
| **Miami-Dade County open data** (Utility Coordination layers + the county's conflict list) served by **Esri ArcGIS Online** (`services.arcgis.com/8Pc9XBTAsYuxx9Ny`, item metadata from `www.arcgis.com`) | public data service | the backend reads it (only when the analysis is used) | the queries only (layer, fields, object IDs) and the server's IP address — nothing about the learner (see §3b) |
| **OpenStreetMap tile servers** (`tile.openstreetmap.org`, OpenStreetMap Foundation) | map tiles | the viewer's browser (only when the analysis map is shown) | the visible map area, the viewer's IP address, browser and the page address (Referer) (see §3b) |
| **Stack Exchange API 2.3** (Stack Overflow questions and answers; a tag's top answerers; still unsolved questions) | public Q&A service | the backend reads it (only when the hackathon hub searches, finds mentors or fills the help board) | the search words — a signature of the error with the learner's paths, hosts, ports, e-mails and key-like strings removed —, tags of the stack, and the server's IP address (see §3c) |
| **GitHub REST API** (`api.github.com`: issue, repository and user search; public profiles and repositories) | public code-hosting API | the backend (hub searches; teammate searches; a card's GitHub check) | search words; for teammates a GitHub language and the event's city (`language:"Svelte" location:"Miami"`) and the logins of the profiles found; the GitHub username of a person who typed it on their card and ticked the box; the server's IP address; an optional `GITHUB_TOKEN` (see §3c) |
| **npm registry** (`registry.npmjs.org`) and **PyPI JSON API** (`pypi.org/pypi`) | package metadata | the backend (hub searches) | the package names an error names or the learner mentions (see §3c) |
| **DEV Community (Forem) API** (`dev.to/api/articles`) | public articles | the backend (hub learning searches) | a topic tag (see §3c) |
| **Google MediaPipe Face Landmarker** (`face_landmarker.task`, float16 v1) | ML model | locally, CPU | camera frames (in memory only) |
| **EmotiEffLib `enet_b0_8_va_mtl`** (ONNX) | ML model (facial expression) | locally, CPU | a face crop of the camera frame (in memory only) |
| **Silero VAD v5** (ONNX) | ML model (voice activity) | locally, CPU | microphone audio (in memory only) |
| **Google MediaPipe Tasks usage metrics** | telemetry built into the MediaPipe wheel | Google servers | usage/performance metrics — per Google not images (see §4) |
| **Cloudflare Tunnel** + `cloudflared` (only for the remote demo; the owner's Cloudflare account) | HTTPS reverse tunnel / CDN edge | Cloudflare edge + a Windows service on the presenter's PC | **all traffic between the demo laptop and the PC**: camera frames, microphone audio, chat text, her voice — TLS terminates at Cloudflare's edge, which re-encrypts it into the tunnel (see §3a) |
| Python libraries (FastAPI, uvicorn, pydantic, openai, numpy, mediapipe, OpenCV, onnxruntime, ormsgpack, websockets, shapely/GEOS, httpx, …) | code | locally | — |
| JavaScript libraries (Svelte, SvelteKit, Vite, lucide, markdown-it, Leaflet) | code | browser / build | — |
| MediaPipe test portrait; a Windows system voice (SAPI) | test assets generated/downloaded at test time, not committed | locally | — |
| AzIAIBetter (the author's own earlier project) | design + code reference | — | — |
| Claude Code (Anthropic, model Claude Opus 5.5) | AI coding assistant used to build the project | development only | the repository contents during development |
| ChatGPT (OpenAI) | AI assistant the team used for some ideas and implementations | development only | what the team typed into it (outside this repository) |
| **ExtraHorizon logo** (`docs/brand/logo-original.svg` → `frontend/static/logo.svg`, `favicon.svg`, `favicon-32.png`, `apple-touch-icon.png`, `components/Logo.svelte`) | brand asset provided by the project owner; made with **Recraft AI** (per its Content Credentials) | shipped with the UI as static files — nothing is fetched | — |

Nothing else is contacted at runtime: no analytics of our own, no external fonts or CDNs
(system fonts only; Leaflet is bundled), no accounts, no cloud storage, no database. Cloudflare is in the path only
when the remote demo is used (§3a); the county's ArcGIS services and OpenStreetMap's tile servers only when the
utility-coordination analysis is used (§3b); a local run without them touches none of these.

---

## 2. Runtime services: OpenAI (LLM + speech-to-text)

### 2.1 Chat (the tutor's answers)

* **API:** Chat Completions with streaming (`POST https://api.openai.com/v1/chat/completions`) via the official `openai` Python SDK; `GET /v1/models/{model}` for the optional deep health check.
* **Model:** `gpt-6-luna` with `reasoning_effort: "none"`, `max_completion_tokens: 600` — chosen by a latency/instruction-following benchmark on 2026-09-25 (median time-to-first-token 0.49 s in isolation; 0.8–1.6 s measured inside the live voice loop). Fallback `gpt-5.5` only if the primary model is rejected as unknown (HTTP 404) before streaming. Both configurable (`EH_LLM_MODEL`, `EH_LLM_FALLBACK_MODEL`).
* **Data sent:** the system prompt (the tutor persona "Rika" and her voice-cue rules, `backend/extrahorizon/context.py`), up to 10 previous exchanges of the session (text only; an interrupted answer is marked as such), for a spoken question a short note saying it was spoken, and — only when exactly one face is clearly in view and the learner's relaxed face has been calibrated — **a short words-only description of the learner's apparent facial expression**, phrased as what the tutor sees on the video call (e.g. *"[What you see on the learner's webcam right now] The learner looks mostly annoyed. Visible right now: frowning, brows pulled down. Overall mood: negative, moderate energy."* — no numbers, no images, no landmarks; during the Demo simulation it is labelled as a simulation), then the new message. Nothing else from the camera. The persona is told that a face shows how someone looks, not what they feel, to mention it rarely and to believe the learner when they say it is wrong; the UI labels every reading as an estimate.

* **Analysis turns** (docs/ANALYSIS.md): instead of the tutoring context, a **fact sheet** of the utility-coordination analysis — the data source and read time, record totals and exclusions by reason, the plans, the rules, finding counts, the county cross-check, findings per pair of plans and the highlighted findings (plan, project name and ID, status, dates, distance or shared area, days together, county-list status) — public Miami-Dade County records; the contact e-mails and phone numbers in those records are never included. `max_completion_tokens: 3000` for the written report. In follow-up questions the request also offers four **function tools** (`find_findings`, `get_project`, `show_on_map`, `recheck_finding` — OpenAI tool calling, `tool_choice: auto`); what they return (more of the same public county records, and a live re-check's result) is sent back to the model in the next round.

### 2.2 Speech-to-text

* **API:** Realtime API in transcription mode over WebSocket, `wss://api.openai.com/v1/realtime?intent=transcription`, session `type: transcription`, model `gpt-live-transcribe`, audio `pcm` 24 kHz, `noise_reduction: far_field`, `turn_detection: null` (turn-taking is done locally, see Silero VAD §3.3), a transcription prompt with domain vocabulary plus the tutor's last words (improves recall of terms like "base case" in noise).
* **Why this model:** measured on 2026-09-26 with noisy speech (pink noise, SNR ≈ 5 dB, English and Russian) streamed in real time against `gpt-4o-transcribe`, `gpt-4o-mini-transcribe`, `gpt-realtime-whisper` and `gpt-transcribe`: all were accurate; `gpt-live-transcribe` was the only one streaming words *while* speaking and delivered the final transcript ≈0.35–0.55 s after the end of speech.
* **Data sent:** only audio the local voice detector classified as speech (plus 400 ms before its onset so the first syllable is not lost). Silence and background noise between utterances never leave the computer.

### 2.3 Keys and offline alternatives

* `OPENAI_API_KEY` lives in the repo-root `.env` (git-ignored); read only by the backend; never logged, never returned to the browser (error texts are sanitised). `.githooks/pre-commit` + `pre-push` and `backend/tests/test_secrets.py` block committing keys, `.env` files or the literal values of any secret in the local `.env`.
* `EH_LLM_PROVIDER=mock` / `--mock-llm` — a labelled, scripted test double (offline); `EH_STT_PROVIDER=mock` / `--mock-voice` — a scripted transcript. Used by the automated tests; they are not additional integrations.
* Use of the OpenAI API is subject to OpenAI's terms and usage policies.

## 3. Runtime service: Fish Audio (the tutor's voice)

* **API:** live TTS over WebSocket with MessagePack frames: `wss://api.fish.audio/v1/tts/live/with-timestamp` (the `drama-*` models are served only on this endpoint), headers `Authorization: Bearer $FISH_API_KEY` and `model: drama-3-preview`; events `start` (reference_id, `format: pcm`, 44.1 kHz, `latency: balanced`, `chunk_length`, temperature/top-p), `text` + `flush` per chunk, `stop`; server events `audio` / `finish` / `error`.
* **Model and voice:** `drama-3-preview` (Fish Audio's expressive model) with the voice (reference model) `c5d8a284092847df9e3c7308aeedc5f2` from the Fish Audio voice library, chosen by the project owner. Voice cues follow Fish Audio's emotion-control documentation (https://docs.fish.audio/developer-guide/core-features/emotions): square-bracket cues at sentence starts, free-form delivery descriptions for drama models, sound effects such as `[sighing]`, `[laughing]`, pauses `[break]` / `[long-break]`, `[emphasis]`.
* **Data sent:** the tutor's answer text as it streams (cut into sentence/clause chunks, markdown and code removed, voice cues kept) and, once at start-up, nine short filler phrases ("Hmm...", "Uhh... let me see.", "Hmph." …) whose audio is cached locally in `backend/cache/fillers/` (git-ignored) so they play instantly.
* **Key:** `FISH_API_KEY` in the git-ignored `.env`, same protections as the OpenAI key. `EH_TTS_PROVIDER=mock` / `--mock-voice` replaces the voice with a labelled offline tone (tests).
* Use of Fish Audio is subject to Fish Audio's terms of service; rights to the selected voice model are governed by its owner's settings on Fish Audio.

## 3a. Remote demo only: Cloudflare Tunnel

* **What:** the presenter's PC runs ExtraHorizon on `127.0.0.1` and Cloudflare's `cloudflared` connector (a
  Windows service, installed and configured by the owner in their own Cloudflare account — not bundled with the
  project). The demo laptop opens the public HTTPS name; Cloudflare's edge forwards the traffic through the tunnel.
  Setup and security model: `docs/REMOTE_DEMO.md`; runner: `scripts/demo-host.ps1`.
* **Data it sees:** everything the laptop's browser exchanges with the PC — camera frames (JPEG, ≤ 8 fps), the
  microphone stream (PCM16), chat text, the tutor's voice audio, the access-key login. TLS is terminated at
  Cloudflare's edge (Cloudflare can technically read the traffic) and re-encrypted into the tunnel. Cloudflare
  adds request headers such as `CF-Connecting-IP`, which ExtraHorizon uses to recognise remote browsers.
* **Honest wording:** as soon as the server reports the Cloudflare transport, the privacy card, the camera and
  microphone consent texts and the status line say that frames and audio travel through Cloudflare to the
  presenter's computer; the "video stays on this device" claim is never shown remotely.
* **Protection:** an access key (`EH_ACCESS_KEY`, git-ignored, secret-guarded) → a signed HttpOnly cookie; brute-force
  brake; same-origin checks. Recommended in addition: Cloudflare Access (Zero Trust) email policy on the hostname.
* **Terms:** Cloudflare's own terms/privacy policy apply to the owner's account; ExtraHorizon adds no Cloudflare
  code, SDK or account of its own.

## 3b. Utility-coordination analysis: Miami-Dade County open data (Esri ArcGIS Online) + OpenStreetMap tiles

* **Data:** Miami-Dade County's public **Utility Coordination** feature layers (water, sewer, reclaimed water,
  stormwater, power, gas, cable, roadway, paving, bridge, transit, canal, miscellaneous, moratorium), the county's
  **Potential Collaboration Project** list and its **Miami-Dade Boundary** polygon (item
  `cec575982ea64ef7a11e587e532c6b6a`, used for "inside the county", generalised to ≈30 m), published by the county's
  ArcGIS Online account `MDPublisher`
  (organisation `8Pc9XBTAsYuxx9Ny`; open-data portal https://gis-mdc.opendata.arcgis.com). Read with the ArcGIS REST
  API over HTTPS by `backend/extrahorizon/coord/arcgis.py` (`/FeatureServer/0?f=json`, `/query` for counts,
  attributes and GeoJSON footprints in WGS84) and `https://www.arcgis.com/sharing/rest/content/items/<id>` for each
  item's owner, access and modified date (the "publisher" check). No key, no account. Kept in memory 6 h; the last
  good copy of each layer in `backend/cache/coord/` (git-ignored), used only if a live read fails and then labelled.
  The data remains the county's; use is subject to Miami-Dade County's open-data terms and Esri's terms of use. Today's
  counts are in docs/ANALYSIS.md.
* **Map tiles:** OpenStreetMap's standard tiles from `https://tile.openstreetmap.org/{z}/{x}/{y}.png`, requested by the
  viewer's browser through Leaflet while the analysis map is visible, shown darkened with a CSS filter. Map data
  © OpenStreetMap contributors, **ODbL 1.0**; attribution is shown on the map. The tile servers are run by the
  OpenStreetMap Foundation under its tile usage policy (light, interactive use with attribution — a hackathon demo);
  they see the viewer's IP address, browser and the page address. The e2e tests block these requests. (A CARTO
  basemap was used during development until it started requiring an API key; it is no longer used.)
* **Test fixtures:** `backend/tests/fixtures/coord/` is synthetic TEST data invented for this project
  (`make_coord_fixtures.py`), labelled as such everywhere; not county data.

## 3c. Hackathon hub: Stack Exchange (Stack Overflow), GitHub, npm, PyPI, DEV Community

Only when the hub searches (a roadblock, a learning topic, teammates, mentors), fills the help board's open questions,
or checks a card's GitHub account. All read-only, over
HTTPS, by `backend/extrahorizon/hub/sources.py` with the User-Agent `ExtraHorizon-hackathon-hub/1.0 (student project;
+https://github.com)`; responses are cached in memory for an hour (`EH_HUB_CACHE_TTL_S`). Details: docs/HUB.md.

* **Stack Exchange API 2.3** — `GET /search/advanced` (questions with answers for the error's signature, one tag),
  `GET /answers/{ids}` (their accepted answers, with bodies) and `GET /questions/{ids}/answers` (their other answers),
  `GET /questions?tagged=…&sort=votes` (learning), `GET /tags/{tag}/top-answerers/{all_time|month}` (mentors: public
  experts for the stack — display name, reputation, answers and score on the tag), `GET /questions/unanswered?tagged=…`
  (the help board: still unsolved questions — title, tags, date, views, the asker's display name). No key:
  300 requests per day per IP; the API's `backoff` is respected. Stack Overflow content is licensed **CC BY-SA 4.0**:
  the hub shows short excerpts with the author's display name, a link to the author, the licence and a link to the
  answer. What is sent: the signature (e.g. `ModuleNotFoundError No module named 'cv2'`) and a tag — the text is
  scrubbed before the signature is taken from it, so never the learner's paths, URLs, hosts, IP addresses, ports,
  `host=` / `password=` values, e-mails, key-like strings (API keys, JWTs, cloud keys), UUIDs, long hex or
  random-looking strings, long numbers or their own file names (tests check it).
* **GitHub REST API** — `GET /search/issues` (the stack's own tracker first, then everywhere), `GET
  /search/repositories` (`<topic> example`, `<topic> tutorial`), `GET /search/users` (teammates: `type:user
  language:"<Lang>" repos:>=3 location:"<city>"` — the event's city, `EH_HUB_EVENT_LOCATION`, or the place the
  question names) and `GET /users/<name>` + `GET /users/<name>/repos` — for the first few profiles such a search
  finds, and for a board card whose author typed a username and ticked the box (public, non-fork repositories:
  language, topics, name, last push; from the profile: login, public name, city, "available for hire", followers,
  since when, and a few words the bio uses — **never the e-mail, blog, company, social accounts or the bio text**;
  nothing is combined with other sources). The hub cannot check that a card's account belongs to whoever typed it and
  never claims so; people found by search are labelled as public leads, not participants. Without a token: 10
  searches per minute and 60 other requests per hour per IP (a teammate search reads at most five profiles).
  An optional `GITHUB_TOKEN` in `.env` (a token with no scopes is enough) raises the limits; it is sent only to
  `api.github.com`, never logged, never shown in the UI (health says only whether one is set).
* **npm registry** — `GET https://registry.npmjs.org/<name>/latest` (version, `engines.node`, `peerDependencies`,
  `deprecated`); **PyPI** — `GET https://pypi.org/pypi/<name>/json` (version, `requires_python`, `yanked`, project
  URLs, the latest upload date). Package names only.
* **DEV Community (Forem) API** — `GET https://dev.to/api/articles?tag=<tag>&top=365` (title, description,
  reactions, reading time, date, author name).
* **The board** is local: `backend/data/hub_board.json` (git-ignored), written by the server; people's cards, help
  requests and shared fixes as their owners wrote them, visible to everyone using this app, until deleted. The
  browser keeps its board token and a copy of the ship plan in localStorage and sends the token with every hub
  request to this server (the `X-Hub-Token` header — in the remote demo through Cloudflare, like everything else);
  the server keeps only its SHA-256.
* **No samples; fixtures only in tests**: the board holds only what real people using the app wrote. The TEST
  fixtures in `backend/tests/fixtures/hub/` (`make_hub_fixtures.py`) are invented, labelled "TEST" (questions, people,
  experts) and link to example.org — not real Stack Overflow, GitHub, npm, PyPI or DEV content. Tests and the offline
  e2e never contact these services (`EH_HUB_OFFLINE_DIR`).

## 4. Local ML models

All three are downloaded on first use / by `scripts/setup.*` from a **pinned URL**, verified by
**SHA-256** after download, stored in `backend/models/` (git-ignored) and run on the CPU.

### 4.1 Google MediaPipe Face Landmarker — and its telemetry

* **Package:** `mediapipe==1.0.1` (Apache-2.0), Tasks API `FaceLandmarker`, VIDEO running mode, CPU (XNNPACK).
* **Model file:** `face_landmarker.task` (float16, version 1, 3,758,596 bytes) from `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task`, SHA-256 `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`. License: Apache-2.0 (Google MediaPipe models).
* **What it computes for us:** how many faces are in view (never reading one of several faces), 478 landmarks (to rotate the face upright and crop it for the expression model), the head pose (turned-away faces become *unknown*; small pose changes lower a frame's weight) and the 52 blendshapes (facial actions such as smile, raised upper lip, jaw open — compared with the learner's calibrated relaxed face to nudge which expression is shown, and named in the note when they fit it, e.g. "baring teeth"). Frames are decoded, analysed and discarded in memory.
* **Telemetry (important):** the official MediaPipe wheels contain a Google usage-logging client (`ClearcutLoggingClient`, endpoint `https://play.googleapis.com/log`). Google's MediaPipe Tasks privacy notice: *"MediaPipe Tasks APIs send metrics about the performance and utilization of the APIs in your app to Google"*; input images/video are processed on device and not sent. **Our measurement** (Windows, 2026-09-26): with a face landmarker running and no other network activity, the process opened an HTTPS connection to a Google server about 60 s into a camera session and when a session was closed. No documented switch disables it, so ExtraHorizon starts the camera only after an explicit click on a card that discloses the metrics, does not create a MediaPipe session at server start, and says so in the privacy card, README and pitch.

### 4.2 EmotiEffLib facial-expression model `enet_b0_8_va_mtl`

* **Source:** EmotiEffLib (formerly HSEmotion) by A. V. Savchenko et al., `https://github.com/sb-ai-lab/EmotiEffLib` (code: Apache-2.0). File `models/affectnet_emotions/onnx/enet_b0_8_va_mtl.onnx` pinned to commit `af833487321c3efdcb1768a91a6c656a1986fdf6`, 16,049,834 bytes, SHA-256 `c43e056ad388d4a8dc911832b8291435b2af537f967e5870ebd731574ec7e812`.
* **What it is:** EfficientNet-B0 multi-task model: 8 expression classes (anger, contempt, disgust, fear, happiness, neutral, sadness, surprise) + valence + arousal from a 224×224 face crop; ≈6 ms per face on a laptop CPU via onnxruntime (we classify an upright square face crop together with its mirror image in one batch, ≈10 ms, and average the logits). ExtraHorizon does not use its raw output directly: a per-person calibration (`backend/extrahorizon/emotion/calibration.py`, our own code — no additional model or dataset) makes the learner's relaxed face read neutral and reports an expression when the face moves clearly away from it. During development the four other EmotiEffLib ONNX models from the same pinned commit (`enet_b0_8_best_afew`, `enet_b0_8_best_vgaf`, `enet_b2_7`, `enet_b2_8`) were downloaded to a temporary folder and compared on the learner's shared frames; none read their relaxed face as neutral (anger 0.69–0.97), so the model stayed and the calibration changed. They are not part of the project. We chose it over the 7/8-class `…_best_vgaf` variant because it also yields valence/arousal (used for the mood map and the note) — compared on the MediaPipe test portrait during development.
* **Caveats we state honestly:** the weights were trained on **AffectNet**, a dataset licensed for non-commercial research; ExtraHorizon uses them for a non-commercial hackathon demo. Facial-expression classifiers are known to be imperfect and biased across people, lighting and cultures; they estimate how a face *looks*, not what anyone feels. On a real user's relaxed face the raw model said "anger 0.90–0.97" — the reason for the per-person calibration, which removes one person's resting-face bias but not every error (which expression is shown still comes from the classifier). The UI (every reading labelled as an estimate) and the persona rules (a face is not a feeling; mention it rarely; believe the learner's correction) reflect this.
* **Research reference:** A. V. Savchenko, "Facial expression and attributes recognition based on multi-task learning of lightweight neural networks", IEEE SISY 2021; A. V. Savchenko, L. V. Savchenko, I. Makarov, "Classifying emotions and engagement in online learning based on a single facial expression recognition neural network", IEEE Transactions on Affective Computing, 2022.

### 4.3 Silero VAD v5

* **Source:** `https://github.com/snakers4/silero-vad` (MIT), file `src/silero_vad/data/silero_vad.onnx` pinned to commit `bfdc0193023f121ea5b3cc7b176dbed570a68a59`, 2,327,524 bytes, SHA-256 `1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3`.
* **Used for:** deciding locally when the learner starts/stops speaking (32 ms windows at 16 kHz, ≈0.1–0.3 ms each), the stricter barge-in bar while the tutor's voice is audible, and keeping silence/noise away from the transcription service. Checked here at SNR ≈ 5 dB.

## 5. Python packages (backend, managed by uv)

Direct dependencies (`backend/pyproject.toml`):

| Package | Version | License | Used for |
|---|---|---|---|
| fastapi | 0.141.1 | MIT | HTTP API, SSE, WebSocket routes |
| uvicorn[standard] | 0.54.0 | BSD-3-Clause | ASGI server (+ httptools, websockets, watchfiles) |
| pydantic | 2.13.5 | MIT | request validation |
| pydantic-settings | 2.15.0 | MIT | configuration from env / `.env` |
| openai | 3.19.2 | Apache-2.0 | OpenAI streaming chat client |
| numpy | 2.5.3 | BSD-3-Clause (+ bundled licenses) | frames, audio buffers |
| mediapipe | 1.0.1 | Apache-2.0 | Face Landmarker (§4.1) |
| onnxruntime | 1.30.0 | MIT | runs the expression model and Silero VAD |
| ormsgpack | 1.12.2 | Apache-2.0 OR MIT | Fish Audio WebSocket frames (MessagePack) |
| websockets | 17.1 | BSD-3-Clause | client WebSockets to Fish Audio and OpenAI Realtime |
| shapely | 2.1.2 | BSD-3-Clause (wheels bundle **GEOS 3.13.1**, LGPL-2.1) | analysis footprints: validity repair, STR-tree index, distances, intersections, simplification |
| httpx | 0.28.1 | BSD-3-Clause | the ArcGIS REST client of the analysis; also the test client and `demo_check.py` |
| pytest *(dev)* | 9.1.1 | MIT | tests |
| pytest-asyncio *(dev)* | 1.4.0 | Apache-2.0 | async tests |

Notable transitive packages: starlette 1.7.0 (BSD-3-Clause), anyio 4.15.1 (MIT),
opencv-contrib-python 5.0.0.93 (Apache-2.0; JPEG decode, colour conversion, the face crop,
test tooling — pulled in by mediapipe), absl-py, flatbuffers, protobuf, certifi, matplotlib
(PSF-based) and sounddevice (MIT) — the last two are required by the mediapipe wheel but not
used by ExtraHorizon. Build backend: hatchling (MIT).

## 6. JavaScript packages (frontend, npm)

| Package | Version | License | Used for |
|---|---|---|---|
| svelte | 5.57.1 | MIT | UI framework (runes) |
| @sveltejs/kit | 2.70.3 | MIT | app framework (SPA, prerendered shell) |
| @sveltejs/adapter-static | 3.0.10 | MIT | static build served by FastAPI |
| @sveltejs/vite-plugin-svelte | 7.3.1 | MIT | build |
| vite | 8.3.1 | MIT | dev server (proxy) and bundler |
| @lucide/svelte | 1.48.0 | ISC | icons (only the imported ones are bundled) |
| markdown-it | 15.0.2 | MIT | rendering answers (`html: false` → model HTML is escaped); a small local plugin renders voice cues |
| leaflet | 1.9.4 | BSD-2-Clause | the analysis map (bundled by Vite with its CSS; tiles from OpenStreetMap, §3b) |
| vitest *(dev)* | 5.0.2 | MIT | unit tests |
| svelte-check *(dev)* | 4.7.6 | MIT | type/a11y checks |
| @playwright/test *(dev)* | 1.63.0 | Apache-2.0 | browser e2e tests (drives the installed Microsoft Edge; no browser download) |

Browser platform APIs used (no library): `getUserMedia` (camera, microphone with the browser's
echo cancellation, noise suppression and auto gain, a chosen input device), `enumerateDevices` (the
microphone list; labels only after permission, nothing leaves the browser), Web Audio (`AudioWorklet` for microphone
capture/resampling to 24 kHz PCM16, gapless playback of the streamed voice), WebSocket,
BroadcastChannel, OffscreenCanvas.

Known advisory: `npm audit` reports a low-severity issue in `cookie <0.7.0` via
`@sveltejs/kit` (server-side cookie parsing). ExtraHorizon ships a static build served by
FastAPI, so SvelteKit's server runtime never runs in the demo.

## 7. Toolchain

Python 3.14.7 (CPython, managed by uv) · uv 0.12.5 · Node.js 24.19.0 / npm 11.17.0 ·
Git 2.55 · Microsoft Edge (for Playwright) · PowerShell / Git Bash (scripts).
Chromium flags used only in tests: `--use-fake-ui-for-media-stream`,
`--use-fake-device-for-media-stream`, `--use-file-for-fake-video-capture`,
`--use-file-for-fake-audio-capture`, `--autoplay-policy=no-user-gesture-required`,
`--host-resolver-rules` (development check through the real tunnel while the PC's DNS cache was stale).
Windows tools used by `scripts/demo-host.ps1`: Task Scheduler (optional autostart), `powercfg` (read-only
sleep check), `curl.exe` and `Resolve-DnsName` (public URL check), `SetThreadExecutionState` (keeps the PC
awake only while the demo host runs).

## 8. Assets used only for testing and development

* **MediaPipe test portrait** — `https://storage.googleapis.com/mediapipe-assets/portrait.jpg` (MediaPipe's public test assets). Downloaded at test time into `backend/tests/.cache/` (git-ignored); used by the vision tests and to build `.y4m` "virtual camera" clips (`backend/scripts/make_fake_camera.py` → `frontend/e2e/.cache/`, git-ignored) so the e2e tests exercise the real camera path without anyone's face. Not redistributed.
* **Windows system voice (SAPI, `System.Speech`)** — `backend/scripts/make_fake_mic.py` synthesizes "Explain recursion to me, please." offline into a `.wav` "virtual microphone" (git-ignored) so the e2e test exercises the real microphone → VAD → turn → playback path without anyone speaking. Windows only; the voice test is skipped elsewhere.
* **OpenAI `gpt-4o-mini-tts`** (voice *alloy*) — used **during development only**, outside the repository, to synthesize three test sentences (English/Russian) that were mixed with generated noise to measure speech-to-text accuracy/latency and voice detection. Not part of the app or the tests.

## 9. Design and code references

* **AzIAIBetter** (`F:\TinyTools2\AzIAIBetter`, the project owner's own earlier project):
  * UI design language (web console, Svelte 5): the "one material" plane/raise/well tokens with sheen and depth levels, grain + dot-grid background, cursor spotlight, the focus "beam" around the composer, chrome logo text, motion rules, and the Vite proxy keep-alive agent (fixes intermittent ECONNRESET on Windows) — adapted and re-coloured.
  * Fish Audio integration know-how and code structure (`src/azi/tts/fish_ws.py`, `tts/silence.py`, `docs/drama3_voice.md`): that `drama-*` models only work on `/v1/tts/live/with-timestamp` with the `model` header, `latency: balanced`, a warm connection pool, starting the voice before the LLM's first words, trimming drama's multi-second pauses, a watchdog and a breaker. Re-implemented for this project (`backend/extrahorizon/voice/fish.py`, `silence.py`).
* **Chart colours and chart rules** — the eight emotion colours are the documented dark categorical steps of the reference palette in Claude Code's bundled *dataviz* skill, with a stacking order chosen by enumerating orderings and validating them with that skill's `validate_palette.js` on this app's chart surface `#0e1629` (lightness band, chroma floor, contrast ≥ 3:1: pass; worst adjacent CVD ΔE 9.4; normal-vision ΔE 19.3); plus its mark/interaction rules (hairline grid, 2 px surface gaps, legend + direct labels, hover crosshair with every series, table view).
* **Analysis colours** — the two compared plans use blue `#3987e5` and orange `#d95926`, steps of the same *dataviz* reference palette, validated with `validate_palette.js --pairs all` on the map surface `#1b1c1e` (lightness band, chroma floor, contrast ≥ 3:1: pass; CVD ΔE 26.8, normal-vision ΔE 31.8); other plans in recessive gray, overlaps in near-white; the basemap is turned gray so only the data carries hue.
* **Icons** — Lucide (ISC). **Fonts** — system fonts only.
* **Logo** — the project owner's "EH" mark with its horizon arc (white on transparent), supplied as an SVG on
  2026-09-26 and kept unchanged as `docs/brand/logo-original.svg`. Its embedded **C2PA Content Credentials**
  (issuer recraft.ai) say *"Created by Recraft AI"* and *"Composed in the Recraft editor"* (title "Recraft AI Generated
  Image"). Derived for the app, colours untouched: `frontend/static/logo.svg` (the mark with the empty margin of the
  1254×1254 canvas cropped and the 39 KB credentials block left out — they stay with the original),
  `frontend/static/favicon.svg` and `components/Logo.svelte` (the mark on the app's navy tile `#0b1224`, because a
  white mark disappears on light tab strips and pages), and `favicon-32.png` / `apple-touch-icon.png` rendered from
  them with Edge. The README shows the tile.

## 10. Research references

* Facial expression → affect: A. V. Savchenko et al. (EmotiEffLib papers above); A. Mollahosseini, B. Hasani, M. H. Mahoor (2017), *AffectNet: A Database for Facial Expression, Valence, and Arousal Computing in the Wild*, IEEE Transactions on Affective Computing.
* Valence–arousal (circumplex) model: J. A. Russell (1980), *A circumplex model of affect*, Journal of Personality and Social Psychology 39(6).
* Limits of inferring emotion from faces: L. F. Barrett et al. (2019), *Emotional Expressions Reconsidered*, Psychological Science in the Public Interest 20(1) — the reason the UI and the prompt speak of *apparent* expressions and estimates.
* Google, *MediaPipe Face Landmarker* documentation and *MediaPipe Tasks privacy notice*; Fish Audio developer guide (emotion control); OpenAI Realtime API transcription guide.

No data or code from these works is used beyond the models listed in §4.

## 11. AI assistance used to build ExtraHorizon

* **Claude Code** (Anthropic's agentic coding tool, desktop app) running **Claude Opus 5.5** (`claude-opus-5-5`) designed and wrote the backend, frontend, tests, scripts, documentation and the project skills in `.claude/skills/`, following the team's implementation brief (`ExtraHorizon_ShellHacks_Implementation_Prompt.md`) and the owner's follow-up requirements (emotion recognition and visualisation, Fish Audio voice with emotion cues, the tsundere persona, real-time voice with interruptions and fillers; then per-person emotion calibration, microphone selection and the persona's video-call behaviour; then styled select boxes and the remote demo through Cloudflare Tunnel with an access key; then the utility-coordination analysis from the hackathon challenge text the owner supplied — compare at least two utilities' public future construction plans, flag overlaps in space or time, verify everything, explain it in the dialogue and show it visually). It ran the tests, the model and provider measurements, the browser checks and the live voice probes reported here. To reproduce a false "angry" reading, it analysed two screenshots of the camera panel that the owner shared in the chat, with the local models only; the images and crops are not part of the repository.
* Independent Claude sub-agents performed read-only code reviews; confirmed findings were fixed and re-tested.
* **ChatGPT** (OpenAI) was used by the team for some of the ideas and implementations (outside this repository; no
  ChatGPT output is fetched or called by the app).
* The **logo** was made with **Recraft AI** (per the Content Credentials of the original file, see §9).
* Claude Code skills used during development: *dataviz* (palette + validator + chart rules), *skill-creator* (format of the project skills).
* At runtime the answers are generated by OpenAI (§2) and voiced by Fish Audio (§3); no Anthropic model is called by the app.
* The human team (repository owner) provided the brief, the reference project, the API keys and the voice choice, and is responsible for the live camera/microphone rehearsal (docs/TEST_MATRIX.md lists what was and was not tested by the agent).
