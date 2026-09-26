#!/usr/bin/env bash
# ExtraHorizon — one-time setup (macOS / Linux / Git Bash).  ./scripts/setup.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing '$1' — install it first: $2" >&2; exit 1; }; }
need uv "https://docs.astral.sh/uv/getting-started/installation/"
need node "https://nodejs.org (LTS)"
need npm "comes with Node.js"

echo "== backend: Python deps (uv sync)"
(cd "$root/backend" && uv sync)
echo "== backend: local models (MediaPipe face, EmotiEffLib expression, Silero VAD)"
(cd "$root/backend" && uv run python -m extrahorizon.vision.model_fetch) || echo "Model download failed — vision/voice detection may be unavailable, chat still works. Re-run when online."
echo "== frontend: npm install + build"
(cd "$root/frontend" && npm install --no-audit --no-fund && npm run build)
if [ ! -f "$root/.env" ]; then
  cp "$root/.env.example" "$root/.env"
  echo "Created .env — set OPENAI_API_KEY and FISH_API_KEY in it (they stay local; .env is git-ignored)."
fi
[ -d "$root/.git" ] && git -C "$root" config core.hooksPath .githooks
echo; echo "Done. Start the demo with:  ./scripts/start.sh"
