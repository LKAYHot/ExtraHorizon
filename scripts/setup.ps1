# ExtraHorizon - one-time setup (Windows PowerShell 5.1+ or PowerShell 7).
#   .\scripts\setup.ps1
# Installs backend deps (uv), downloads + verifies the MediaPipe model, installs and
# builds the UI, creates .env from .env.example (never overwrites an existing one) and
# enables the secret-guard git hooks.
$ErrorActionPreference = 'Continue'  # native tools print warnings on stderr; exit codes are checked explicitly
$root = Split-Path -Parent $PSScriptRoot

function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "Missing '$cmd' - install it first: $hint" -ForegroundColor Red
        exit 1
    }
}
Need uv 'winget install astral-sh.uv'
Need node 'winget install OpenJS.NodeJS.LTS'
Need npm 'comes with Node.js'

Write-Host '== backend: Python deps (uv sync)' -ForegroundColor Cyan
Push-Location "$root\backend"
uv sync
if ($LASTEXITCODE) { Pop-Location; exit 1 }
Write-Host '== backend: MediaPipe Face Landmarker model' -ForegroundColor Cyan
uv run python -m extrahorizon.vision.model_fetch
if ($LASTEXITCODE) { Write-Host 'Model download failed - vision will be unavailable, chat still works.' -ForegroundColor Yellow }
Pop-Location

Write-Host '== frontend: npm install + build' -ForegroundColor Cyan
Push-Location "$root\frontend"
npm install --no-audit --no-fund
if ($LASTEXITCODE) { Pop-Location; exit 1 }
npm run build
if ($LASTEXITCODE) { Pop-Location; exit 1 }
Pop-Location

if (-not (Test-Path "$root\.env")) {
    Copy-Item "$root\.env.example" "$root\.env"
    Write-Host 'Created .env - open it and set OPENAI_API_KEY (it stays local; .env is git-ignored).' -ForegroundColor Yellow
}
if (Test-Path "$root\.git") { git -C $root config core.hooksPath .githooks }

Write-Host "`nDone. Start the demo with:  .\scripts\start.ps1" -ForegroundColor Green
