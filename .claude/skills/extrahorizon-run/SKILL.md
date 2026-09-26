---
name: extrahorizon-run
description: Start, stop, restart and health-check the ExtraHorizon voice tutor (FastAPI backend on :8765 serving the built SvelteKit UI, or the Vite dev server on :5173). Use this whenever you need to run the app, see a change in the browser, reproduce a bug, check /api/health, open the UI in the browser pane, switch to the offline mock LLM / mock voice, or when the server "does not start", the port is busy (8765 locally, 8080 for the remote demo host), the UI shows "backend offline", vision says "unavailable", voice is silent, the microphone fails, or chat returns llm_not_configured — even if the user just says "запусти", "run it", "покажи", "перезапусти сервер".
---

# Running ExtraHorizon

Demo mode is one Python process: `backend/` (FastAPI, uv-managed, Python ≥ 3.12) serves the API, both
WebSockets (`/api/vision`, `/api/live`) **and** the prebuilt UI from `frontend/build`. Dev mode adds the Vite
server on :5173, which proxies `/api` (HTTP + WebSockets) to :8765.

## Start

| Goal | Command (repo root) |
|---|---|
| Demo (built UI, real providers) | `.\scripts\start.ps1` → http://127.0.0.1:8765 |
| Offline rehearsal (no keys / internet) | `.\scripts\start.ps1 -MockLLM -MockVoice` (labelled mock tutor, tone voice, scripted transcript) |
| UI hot reload | `.\scripts\start.ps1 -Dev` → http://127.0.0.1:5173 |
| First time on a machine | `.\scripts\setup.ps1` (uv sync, 3 model downloads, npm install + build, .env) |

macOS/Linux/Git Bash: `./scripts/*.sh` (`--mock-llm`, `--mock-voice`, `--dev`, `--open`).

From an agent shell, run the backend in the background and poll health instead of sleeping:

```bash
cd backend && uv run python -m extrahorizon --port 8765 > "$SCRATCH/server.log" 2>&1   # run_in_background
for i in $(seq 1 40); do curl -s -m 1 http://127.0.0.1:8765/api/health >/dev/null && break; sleep 0.5; done
curl -s "http://127.0.0.1:8765/api/health?deep=1"     # deep=1 also pings OpenAI (cheap model lookup)
```

Wait for `"fillers": "ready"` before testing voice (the nine filler clips are synthesized once, then cached in
`backend/cache/fillers/`). The backend mounts the UI only if `frontend/build/index.html` existed **at startup** —
after `npm run build` the files are served fresh, but restart after backend code changes.

## Stop / restart (Windows)

```powershell
$p = (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique
if ($p) { $p | ForEach-Object { Stop-Process -Id $_ -Force } }
```
A killed background task reports exit code 127/1 — that is the kill, not a crash. Restarting changes `boot_id`;
open tabs detect it and clear their view (by design).

## Reading /api/health

- `llm.configured=false` → `OPENAI_API_KEY` missing in the repo-root `.env` (never print keys; check with `len(...)` only).
- `tts.configured=false` → `FISH_API_KEY` missing; `tts.state=down` + `last_error` → Fish unreachable / auth (breaker retries after 30 s).
- `stt.configured=false` → no OpenAI key or `EH_STT_PROVIDER=off`; `stt.vad=false` → Silero model missing (`uv run python -m extrahorizon.vision.model_fetch`).
- `vision.available=false` + `reason` → model missing/download failed or `mediapipe_error` (see the log). Chat and voice keep working.

## Seeing it

Open http://127.0.0.1:8765 in the browser pane. The pane cannot use the camera or microphone — you will see the
"permission denied" paths; drive the emotion panel with the labelled *Demo simulation mode*. **Mute the speaker
toggle in the pane before sending questions** (otherwise her voice plays on the user's speakers). The real camera
and microphone paths are exercised by Playwright with virtual devices (see extrahorizon-test) and by
`backend/scripts/demo_check.py --speech …wav`. Never turn on the user's physical webcam or microphone without asking.

## Remote demo host (home PC behind Cloudflare Tunnel)

`.\scripts\demo-host.ps1` serves on `127.0.0.1:8080` for the tunnel (auto-restart, keeps the PC awake);
`-Check` for its state. Opening `http://127.0.0.1:8080` on the PC itself needs no key; the public URL does.
Everything about the tunnel, the access key and remote troubleshooting: the `extrahorizon-remote-demo` skill.

## Known gotchas

- Windows consoles use cp1251: entry points reconfigure stdout to UTF-8; for ad-hoc Python prints set `PYTHONIOENCODING=utf-8`.
- Port busy → another backend is running; stop it rather than picking random ports (the dev proxy and e2e expect 8765 / 8799).
- `WinError 10022/10054` tracebacks on client disconnect are filtered in `app.py`; other errors still show.
- MediaPipe prints `W0000 ... xnnpack` lines once per camera session — harmless.
- Fish `drama-*` models work only on `/v1/tts/live/with-timestamp` with the `model` header — keep `fish_url()` logic.
