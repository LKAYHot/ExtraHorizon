# ExtraHorizon - run the automated checks.
#   .\scripts\test.ps1          backend pytest + frontend unit tests + svelte-check + build
#   .\scripts\test.ps1 -E2E     ... plus the Playwright browser tests (virtual camera, mock LLM)
param([switch]$E2E)
$ErrorActionPreference = 'Continue'  # native tools print warnings on stderr; exit codes are checked explicitly
$root = Split-Path -Parent $PSScriptRoot
$failed = @()

Push-Location "$root\backend"
Write-Host '== backend: pytest' -ForegroundColor Cyan
uv run pytest
if ($LASTEXITCODE) { $failed += 'pytest' }
Pop-Location

Push-Location "$root\frontend"
Write-Host '== frontend: unit tests' -ForegroundColor Cyan
npx vitest run
if ($LASTEXITCODE) { $failed += 'vitest' }
Write-Host '== frontend: svelte-check' -ForegroundColor Cyan
npx svelte-kit sync | Out-Null
npx svelte-check --threshold warning
if ($LASTEXITCODE) { $failed += 'svelte-check' }
Write-Host '== frontend: build' -ForegroundColor Cyan
npm run build
if ($LASTEXITCODE) { $failed += 'build' }
if ($E2E) {
    Write-Host '== e2e: Playwright (Edge by default; PW_CHANNEL=chrome to switch)' -ForegroundColor Cyan
    npx playwright test
    if ($LASTEXITCODE) { $failed += 'e2e' }
}
Pop-Location

if ($failed.Count) { Write-Host "FAILED: $($failed -join ', ')" -ForegroundColor Red; exit 1 }
Write-Host 'All checks passed.' -ForegroundColor Green
