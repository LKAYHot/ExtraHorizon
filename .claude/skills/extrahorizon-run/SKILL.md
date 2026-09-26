---
name: extrahorizon-run
description: Start, stop, restart and health-check the ExtraHorizon adaptive-tutor app (FastAPI backend on :8765 serving the built SvelteKit UI, or the Vite dev server on :5173). Use this whenever you need to run the app, see a change in the browser, reproduce a bug, check /api/health, open the UI in the browser pane, switch to the offline mock LLM, or when the server "does not start", the port is busy, the UI shows "backend offline", vision says "unavailable", or chat returns llm_not_configured — even if the user just says "запусти", "run it", "покажи", "перезапусти сервер".
---

# Running ExtraHorizon

The app is one Python process in demo mode: `backend/` (FastAPI, uv-managed, Python ≥ 3.12)
serves the API **and** the prebuilt UI from `frontend/build`. Dev mode adds the Vite
server on :5173, which proxies `/api` (HTTP + the vision WebSocket) to :8765.

## Start

| Goal | Command (repo root) |
|---|---|
| Demo (built UI) | `.\scripts\start.ps1` → http://127.0.0.1:8765 |
| Offline rehearsal, no key/internet | `.\scripts\start.ps1 -MockLLM` (answers are labelled *Mock LLM*) |
| UI hot reload | `.\scripts\start.ps1 -Dev` → http://127.0.0.1:5173 |
| First time on a machine | `.\scripts\setup.ps1` (uv sync, model download, npm install + build, .env) |

macOS/Linux/Git Bash: the same with `./scripts/*.sh` (`--mock-llm`, `--dev`, `--open`).

From an agent shell, run the backend in the background and poll health instead of sleeping:

```bash
cd backend && uv run python -m extrahorizon --port 8765 > "$SCRATCH/server.log" 2>&1   # run_in_background
for i in $(seq 1 40); do curl -s -m 1 http://127.0.0.1:8765/api/health >/dev/null && break; sleep 0.5; done
curl -s "http://127.0.0.1:8765/api/health?deep=1"     # deep=1 also pings OpenAI (cheap model lookup)
```

The backend only mounts the UI if `frontend/build/index.html` existed **at startup** —
after `npm run build`, restart the backend (or you will get the "UI is not built yet" page).

## Stop / restart (Windows)

```powershell
$p = (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique
if ($p) { $p | ForEach-Object { Stop-Process -Id $_ -Force } }
```
A killed background task reports exit code 127/1 — that is the kill, not a crash.
Restarting changes `boot_id`; open tabs detect it and clear their view (by design).

## Reading /api/health

- `llm.configured=false` → `OPENAI_API_KEY` missing in the repo-root `.env` (never print the key; check with `len(...)` only).
- `llm.reachable=false` or `last_error` → network / key / model problem; the UI shows it in the sidebar.
- `vision.available=false` + `reason` → `model_missing|model_download_failed` (run `uv run python -m extrahorizon.vision.model_fetch`) or `mediapipe_error` (see server log). Chat keeps working either way.

## Seeing it

Open http://127.0.0.1:8765 in the browser pane. The pane **blocks camera access**, so there
you will always see the "permission denied → Vision unavailable — chat still works" path; use
the labelled *Demo simulation mode* card to drive the engine, or the Playwright e2e run
(virtual camera with a real face) to exercise the real camera path. Never turn on the user's
physical webcam (a Logi C270 is attached) without asking them first.

## Known gotchas

- Windows consoles use cp1251: every entry point calls `stdout.reconfigure(encoding="utf-8")` first — keep that when adding scripts/prints.
- Port busy → another backend is running; stop it (above) rather than picking random ports (the dev proxy and e2e expect 8765 / 8799).
- `WinError 10022/10054` tracebacks on client disconnect are filtered in `app.py` (`_quiet_windows_disconnect_noise`); other errors still show.
- MediaPipe prints `W0000 ... xnnpack` lines once per camera session — harmless.
