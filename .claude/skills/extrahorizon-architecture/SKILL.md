---
name: extrahorizon-architecture
description: Architecture map, API/WebSocket contract and non-negotiable invariants of ExtraHorizon (SvelteKit UI ⇄ FastAPI ⇄ OpenAI, local MediaPipe vision, per-session state engine). Use this BEFORE changing any message, endpoint, event, engine rule, prompt/context text, privacy wording or dependency — and whenever you need to know "where does X live", "what does the UI receive", "what is sent to OpenAI", or when adding a feature (auto-adapt, new strategy, new signal, new provider). Also use it when updating EXTERNAL_DEPENDENCIES.md, README or the pitch.
---

# ExtraHorizon architecture & contract

```
Browser (SvelteKit SPA)                         Python process on the same machine (FastAPI)                 OpenAI
─────────────────────────                       ──────────────────────────────────────────                 ──────
getUserMedia → canvas 480px JPEG ──WS /api/vision──► VisionConnection → FaceAnalyzer (MediaPipe, thread pool)
   (1 frame in flight, ≤12 fps)                        → assess_quality → ConfusionProxy → StateEngine (per session)
tick/event/marker/snapshot  ◄──────────────────────────┘        │ events + timeline
chat (fetch + SSE parser) ──POST /api/chat─────────► Session.plan_chat → context.build_messages ──stream──► chat.completions
   meta/delta/done/error    ◄── SSE ─────────────────── _chat_stream (timeouts, cancel, commit-on-success)
```

Source of truth for every message: **`docs/CONTRACT.md`** — change it first, then both sides,
then tests (`backend/tests/test_api.py`, `frontend/src/lib/*.test.js`, `frontend/e2e`).

## Where things live

| Concern | File |
|---|---|
| Config / all tunables (env `EH_*`) | `backend/extrahorizon/config.py`, `.env.example` |
| Adaptation rule (EMA, hold, cooldown, relief) | `backend/extrahorizon/engine.py` (pure, clock injected) |
| Session state, events, offers, commit/abort, reset | `backend/extrahorizon/sessions.py` |
| What the LLM receives (strategies, adaptation note) | `backend/extrahorizon/context.py` |
| OpenAI streaming, error mapping, fallback model, mock | `backend/extrahorizon/llm.py` |
| HTTP routes, SSE loop, origin/host guards, static UI | `backend/extrahorizon/app.py` |
| Vision socket (latest-frame-wins, single writer) | `backend/extrahorizon/vision_ws.py` |
| Frame analysis / proxy / model download | `backend/extrahorizon/vision/*.py` |
| UI state (the only store), camera + socket | `frontend/src/lib/app.svelte.js`, `vision.svelte.js` |
| Chat streaming client + idle watchdog | `frontend/src/lib/api.js`, `sse.js` |
| Components (sidebar / chat / vision panel) | `frontend/src/lib/components/*.svelte` |
| Design tokens (AzIAIBetter material, navy) | `frontend/src/app.css` |

## Invariants (each is covered by a test — keep them green)

1. **Separation**: signal numbers (UI only) → engine decision (event) → abstract instruction text. The note sent to the LLM has no digits, no images, no landmarks, and never claims to know feelings or mentions the camera.
2. **Unknown ≠ neutral**: missing/ambiguous/poor data resets accumulation and shows "—" with a reason. Two faces never adapt.
3. **Time, not frames**; one event per episode (disarmed until the signal drops below `rearm_threshold` or a new answer arrives) plus the cooldown; decrease claimed only when measured; a closed socket makes the signal `unknown`, never frozen.
4. **Per-tab sessions** (sessionStorage UUID); no shared state; reset clears history, events, timeline, cooldown, baseline and cancels a stream.
5. **Chat never hangs**: every stream ends in `done` or `error` (server timeouts + client idle watchdog); nothing is committed unless `done`; Retry re-sends.
6. **Vision failure never disables chat** — `sessions.py` imports only `vision/types.py`; OpenCV/NumPy/MediaPipe load lazily per camera session (tested with a broken `cv2`).
7. **Privacy claims follow the real data path**: "video stays on this device" is shown only when both the page host and the backend's view of the client are loopback. MediaPipe's own usage metrics to Google are disclosed (consent card, privacy card, README); the camera never starts before the consent click and no MediaPipe task is created at server start.
8. **Simulation is labelled** (SIMULATED chips, striped card, dashed timeline, "not live recognition" in Why-it-adapted) and allowed only in tests / that mode.
9. **Secrets**: the key lives only in the git-ignored `.env`; hooks in `.githooks/` + `tests/test_secrets.py` block commits/pushes of keys. Never print, log or return the key.
10. **One LLM integration** (OpenAI). The mock is a labelled test double, not a second provider. Go service / accounts / billing / voice / cloud sync are out of scope (spec §3).

## When you add or change a dependency, model, dataset, asset or AI tool

Update `EXTERNAL_DEPENDENCIES.md` in the same change (name, version, license, what it is used for,
what data it sees). Hackathon rules require disclosing everything external.
