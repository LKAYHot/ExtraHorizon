# ExtraHorizon — notes for Claude Code

Emotion-aware voice tutor for ShellHacks: SvelteKit UI → Python FastAPI (local MediaPipe + EmotiEffLib
expression model + Silero VAD; per-session calibration, emotion engine and voice turn logic) → OpenAI (chat +
realtime transcription) and Fish Audio (drama-3-preview voice). Persona: **Rika**, a tsundere anime
girl who explains like a rigorous expert, always in English (understands Russian).
Original brief: `ExtraHorizon_ShellHacks_Implementation_Prompt.md`; the follow-up requirements (emotions
instead of confusion, Fish voice with emotion cues, tsundere persona, real-time voice with barge-in and
fillers; then per-person calibration of the expression estimate, microphone choice, and a persona that talks
like a person on a video call and "sees" the learner) are reflected in `docs/`.

Project skills (use them — they hold the procedures and the invariants):

- `extrahorizon-architecture` — where things live, the API/WS contract (`docs/CONTRACT.md`), invariants. Read before changing any message, rule, prompt/persona text or privacy wording.
- `extrahorizon-run` — start/stop/health, demo vs dev vs mock mode, Windows gotchas.
- `extrahorizon-test` — test layers and what each protects; run after every change.
- `extrahorizon-voice` — voice pipeline debugging and tuning (latency, barge-in, echo, STT, Fish).
- `extrahorizon-vision-tuning` — the calibrated facial-expression estimate on a real webcam (ask before turning it on).
- `extrahorizon-demo-rehearsal` — the 60–90 s script, fallbacks, manual matrix, honest claims.
- `extrahorizon-remote-demo` — the home PC behind Cloudflare Tunnel (`scripts/demo-host.ps1`), the access key, remote troubleshooting.

Hard rules:

- API keys (`OPENAI_API_KEY`, `FISH_API_KEY`) and the remote-demo access key (`EH_ACCESS_KEY`) live only in the git-ignored `.env`. Never print, log, commit or send them anywhere; check with `len(...)` only. Hooks in `.githooks/` and `backend/tests/test_secrets.py` enforce this.
- Never turn on the user's physical webcam or microphone without asking. In the browser pane, mute the speaker toggle before sending questions (her voice would play on the user's speakers).
- Keep UI, README, pitch and `EXTERNAL_DEPENDENCIES.md` truthful about data flow (localhost frames; speech segments → OpenAI transcription; text + words-only expression note → OpenAI chat; answer text → Fish Audio; MediaPipe usage metrics → Google; in the remote demo everything between the laptop and the PC → Cloudflare). Update `EXTERNAL_DEPENDENCIES.md` whenever an external dependency, model, asset, service or AI tool changes.
- Simulation input must stay labelled; unknown must never become "neutral"; nothing is reported before calibration; the prompt note must contain no numbers and describes how the learner *looks* (her view on the call), never what they feel; the UI keeps labelling every reading as an estimate.
- Commit or push only when the user asks.
