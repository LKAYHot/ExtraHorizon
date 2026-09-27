<p align="center">
  <img src="frontend/static/favicon.svg" width="128" height="128" alt="ExtraHorizon logo">
</p>

# ExtraHorizon — Rika, an emotion-aware voice tutor you can actually talk to

ExtraHorizon is an AI tutor you **talk to** — hands-free, like a call. **Rika** (a tsundere
anime girl with an expert's rigour) answers **out loud** in an expressive Fish Audio voice.

Built for ShellHacks. Stack: **SvelteKit (Svelte 5), Python FastAPI, OpenAI (chat + realtime
transcription), Fish Audio (drama-3-preview)**, with **MediaPipe**, **EmotiEffLib** and **Silero
VAD** running on the local CPU.

**Utility-coordination analysis.** Ask her *"Where do the utilities' construction plans overlap?"* (or press
**Coordination**): ExtraHorizon reads **Miami-Dade County's public Utility Coordination data** for information.

**Hackathon hub.** Stuck? Paste the error or just say it (*"I'm getting a CORS error from FastAPI"*).

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

| Path | What |
|---|---|
| `backend/extrahorizon/live_ws.py` · `turns.py` | the voice conversation (turn-taking) · one tutor turn (LLM → splitter → voice) |
| `backend/extrahorizon/voice/` | Fish Audio client, fillers, speech-to-text, Silero VAD segmenter, cue handling, splitter, silence cap |
| `backend/extrahorizon/emotion/` · `vision/` | expression model, per-person calibration, emotion engine · MediaPipe analysis, quality gates, model download |
| `backend/extrahorizon/context.py` | what the LLM receives: the Rika persona, voice-cue rules, the expression note |
| `backend/extrahorizon/coord/` | the utility-coordination analysis: sources, ArcGIS client, verification, overlaps, county cross-check, fact sheet + grounding check |
| `frontend/src/lib/components/AnalysisPanel.svelte` · `Coord*.svelte` | the analysis panel: map (Leaflet), findings, schedules, sources & checks |
| `backend/extrahorizon/hub/` | the hackathon hub: error signature + scrubbing, public sources (Stack Exchange, GitHub, npm, PyPI, DEV), verification, board, matching, ship plan, fact sheet |
| `frontend/src/lib/hub.svelte.js` · `components/Hub*.svelte` · `DateTimePicker.svelte` | the hub panel: get unstuck, people, help board, ship (the deadline picker) |
| `backend/extrahorizon/sessions.py` · `app.py` · `vision_ws.py` | sessions/turns/reset · HTTP/SSE/routes · camera socket |
| `frontend/src/lib/` | app store, voice controller + audio (mic worklet with device choice, player), camera controller, components |
| `backend/scripts/` | `demo_check.py` (live chain against the running app), `vision_probe.py` (webcam check), `make_fake_camera.py` / `make_fake_mic.py` (test clips) |
| `docs/brand/` · `frontend/static/` · `components/Logo.svelte` | the logo: the original file (with its Content Credentials) · the mark, the favicon tile and the PNG icons derived from it · the in-app icon |
| `.claude/skills/` | Claude Code skills for running, testing, rehearsing, tuning and the architecture contract |

## Configuration

Every threshold and timing is an environment variable (`EH_*`) with defaults in
`backend/extrahorizon/config.py`; the annotated list is in [.env.example](.env.example) — e.g.
`EH_VAD_END_SILENCE_MS` (how fast she answers), `EH_BARGE_IN_*` (how easily you interrupt her),
`EH_VOICE_MERGE_WINDOW_S`, `EH_EMOTION_SENSITIVITY` / `EH_EMOTION_CALIBRATION_S` / other `EH_EMOTION_*`, `EH_FISH_*`,
for the remote demo `EH_PUBLIC_URL`, `EH_ACCESS_KEY`, `EH_REMOTE_MAX_FPS`, and for the analysis `EH_COORD_DISTANCE_M`,
`EH_COORD_WINDOW_DAYS`, `EH_COORD_AREA_M` (also adjustable in the panel), `EH_COORD_CACHE_TTL_S`.

## AI assistance

ExtraHorizon was built with the help of AI tools:

* **Claude Code** (Anthropic) — used as the coding assistant.
* **ChatGPT** (OpenAI) — used for some of the ideas and implementations.
* The **logo** was made with **Recraft AI** (per the Content Credentials in the original file,
  [docs/brand/logo-original.svg](docs/brand/logo-original.svg)).

Which models, and what each tool was used for: [EXTERNAL_DEPENDENCIES.md §11](EXTERNAL_DEPENDENCIES.md#11-ai-assistance-used-to-build-extrahorizon).
At runtime the app itself calls only the services listed under *Privacy* above.

## License

MIT — see [LICENSE](LICENSE). Third-party components keep their own licenses (see EXTERNAL_DEPENDENCIES.md).
