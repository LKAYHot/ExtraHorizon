#!/usr/bin/env bash
# ExtraHorizon — start the demo.
#   ./scripts/start.sh             backend + built UI  -> http://127.0.0.1:8765
#   ./scripts/start.sh --mock-llm  offline, labelled scripted tutor (no API key / internet)
#   ./scripts/start.sh --open      open the browser when ready
#   ./scripts/start.sh --dev       backend in background + Vite hot-reload UI -> http://127.0.0.1:5173
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
port="${EH_PORT:-8765}"
dev=0; flags=(--port "$port")
for a in "$@"; do
  case "$a" in
    --dev) dev=1 ;;
    --mock-llm|--open|--no-vision) flags+=("$a") ;;
    *) echo "unknown option $a" >&2; exit 2 ;;
  esac
done
if [ "$dev" = 0 ]; then
  [ -f "$root/frontend/build/index.html" ] || (cd "$root/frontend" && npm run build)
  cd "$root/backend" && exec uv run python -m extrahorizon "${flags[@]}"
fi
(cd "$root/backend" && uv run python -m extrahorizon "${flags[@]}") &
backend=$!
trap 'kill $backend 2>/dev/null' EXIT
cd "$root/frontend" && EH_BACKEND="http://127.0.0.1:$port" npm run dev
