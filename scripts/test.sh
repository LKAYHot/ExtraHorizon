#!/usr/bin/env bash
# ExtraHorizon — automated checks.  ./scripts/test.sh [--e2e]
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
failed=()
(cd "$root/backend" && uv run pytest) || failed+=(pytest)
(cd "$root/frontend" && npx vitest run) || failed+=(vitest)
(cd "$root/frontend" && npx svelte-kit sync >/dev/null && npx svelte-check --threshold warning) || failed+=(svelte-check)
(cd "$root/frontend" && npm run build) || failed+=(build)
if [ "${1:-}" = "--e2e" ]; then (cd "$root/frontend" && npx playwright test) || failed+=(e2e); fi
if [ ${#failed[@]} -gt 0 ]; then echo "FAILED: ${failed[*]}"; exit 1; fi
echo "All checks passed."
