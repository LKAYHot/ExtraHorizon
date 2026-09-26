---
name: extrahorizon-test
description: Run and extend the ExtraHorizon automated test suites — backend pytest (state engine, context builder, API with a fake LLM, vision/MediaPipe, secret scan), frontend vitest + svelte-check, Playwright e2e with a virtual camera, and the live demo_check against the real OpenAI model. Use this after ANY code change in backend/ or frontend/, before claiming something works, when a test fails, when adding a feature that needs a test, or when the user asks "проверь", "прогони тесты", "does it still work", "run CI" — even for small edits.
---

# Testing ExtraHorizon

Run the cheapest layer that can catch the bug first, then widen. Everything below runs
without the user's webcam; only `demo_check` touches the real LLM (costs a few cents).

| Layer | Command | Time | Needs |
|---|---|---|---|
| Backend unit + integration | `cd backend && uv run pytest` | ~15 s | nothing (fake LLM) |
| Frontend unit | `cd frontend && npx vitest run` | ~1 s | — |
| Types / a11y / Svelte | `cd frontend && npx svelte-kit sync && npx svelte-check --threshold warning` | ~10 s | — |
| Browser e2e (4 camera setups) | `cd frontend && npm run e2e` | ~1 min | Edge (default) — `PW_CHANNEL=chrome` to switch |
| Live chain, real LLM | backend running, then `cd backend && uv run python scripts/demo_check.py --runs 10` | ~1 min | key in `.env`, internet |
| Everything | `.\scripts\test.ps1 -E2E` | ~2 min | |

## What each suite protects (don't weaken these to make a change pass)

- `tests/test_engine.py` — the adaptation rule: short spikes never fire; ≥ hold_s of wall-clock time fires exactly once; one event per episode (no nagging after the cooldown; re-armed by a real drop or a new answer); dips / unknown / multi-face / data gaps reset the timer; EMA is frame-rate independent; simulation never inherits camera state; decrease is reported only when measured; sessions are isolated; frames in flight after "camera off" are ignored.
- `tests/test_context.py` — no adaptation note before an event; after one: strategy + previous answer in context; the serialized OpenAI payload contains no image/landmark/blendshape data, no signal numbers, no `%`, and the note has **no digits at all**; strategies rotate; the note is not persisted into later turns.
- `tests/test_api.py` — SSE stream delivered to the end and committed; LLM error / mid-stream failure / first-token hang / stall all end with a retryable `error` and commit nothing; retry works; missing key → immediate `llm_not_configured`; vision unavailable or garbage frames never break chat; full chain over HTTP + WS; one event per episode; reset clears everything incl. cooldown; offers expire on a new question; socket supersede; cross-origin blocked.
- `tests/test_vision.py` — quality gates → `unknown` with a reason; calibration is time-based and restarts after a break; proxy behaviour (neutral low, frown high, smile/blink suppression, personal baseline); real MediaPipe on the portrait (pose, darkness gate).
- `tests/test_secrets.py` — no `sk-…` key or `.env` in anything git would commit.
- `frontend/src/lib/vision.test.js` — camera/socket controller with stubbed browser APIs: frames flow whichever of camera or server `hello` comes first (also after a vision error + reconnect); a camera toggled during a pending permission request never keeps capturing.
- `frontend/e2e/*.spec.js` — the 60–90 s demo in a real browser (virtual camera shows a real face; the confusion rise comes from the **labelled** simulation, asserted to be labelled), refresh restore, two faces → ambiguous, no face → unknown, camera off mid-session, permission denied → chat still works.

## Writing new tests

- Test observable behaviour and failure paths, not implementation strings (spec §7).
- Engine/session tests inject time (`Observation(t=...)`, `Session(..., clock=...)`); never `sleep` for engine timing.
- API tests use `conftest.make_settings(...)` (short timings: hold 0.3 s, timeouts 0.4 s) and `FakeLLM(script=[...])` modes `ok|error|hang|stall|fail_mid`. Tests never read `.env` (`_isolate_env` fixture) — keep it that way so the real key is never used by CI.
- Real-image tests use the `portrait_jpeg` / `model_path` fixtures (downloaded once into `backend/tests/.cache`, skipped offline).
- A controlled signal is allowed only in tests or the labelled *Demo simulation mode* (spec §7.4).

## When something fails

1. Read the assertion message; for e2e open `frontend/test-results/*/error-context.md` (page snapshot + call log).
2. Reproduce with the smallest layer (a pytest `-k` filter, or `npx playwright test -g "<title>" --project face`).
3. Fix the code, then rerun the whole layer and the layers above it. Record the result honestly — a skipped or not-run check is reported as such.
