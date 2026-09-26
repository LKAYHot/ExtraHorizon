# ExtraHorizon — notes for Claude Code

Adaptive AI tutor for ShellHacks: SvelteKit UI → Python FastAPI (local MediaPipe vision +
per-session state engine) → OpenAI. The brief is `ExtraHorizon_ShellHacks_Implementation_Prompt.md`.

Project skills (use them — they hold the procedures and the invariants):

- `extrahorizon-architecture` — where things live, the API/WS contract (`docs/CONTRACT.md`), invariants. Read before changing any message, rule, prompt text or privacy wording.
- `extrahorizon-run` — start/stop/health, dev vs demo mode, Windows gotchas.
- `extrahorizon-test` — test layers and what each protects; run after every change.
- `extrahorizon-demo-rehearsal` — the 60–90 s script, fallbacks, manual matrix, honest claims.
- `extrahorizon-vision-tuning` — tuning the confusion proxy on a real webcam (ask before turning it on).

Hard rules:

- The OpenAI key lives only in the git-ignored `.env`. Never print, log, commit or send it anywhere; check with `len(...)` only. Hooks in `.githooks/` and `backend/tests/test_secrets.py` enforce this.
- Never turn on the user's physical webcam without asking.
- Keep UI, README, pitch and `EXTERNAL_DEPENDENCIES.md` truthful about data flow (localhost frames, OpenAI text, MediaPipe usage metrics to Google). Update `EXTERNAL_DEPENDENCIES.md` whenever an external dependency, model, asset or AI tool changes.
- Simulation input must stay labelled; unknown must never become "neutral"; the LLM note must contain no numbers.
- Commit or push only when the user asks.
