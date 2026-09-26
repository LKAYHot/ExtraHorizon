# ExtraHorizon - start the demo.
#   .\scripts\start.ps1              backend + built UI  -> http://127.0.0.1:8765
#   .\scripts\start.ps1 -Open        ... and open the browser
#   .\scripts\start.ps1 -MockLLM     offline, labelled scripted tutor (no OpenAI key / internet)
#   .\scripts\start.ps1 -MockVoice   offline voice doubles (tone instead of Fish Audio, scripted transcript)
#   .\scripts\start.ps1 -Dev         backend in a 2nd window + Vite hot-reload UI -> http://127.0.0.1:5173
param([switch]$Dev, [switch]$MockLLM, [switch]$MockVoice, [switch]$Open, [int]$Port = 8765)
$ErrorActionPreference = 'Continue'  # native tools print warnings on stderr; exit codes are checked explicitly
$root = Split-Path -Parent $PSScriptRoot

$flags = @('--port', "$Port")
if ($MockLLM) { $flags += '--mock-llm' }
if ($MockVoice) { $flags += '--mock-voice' }

if (-not $Dev) {
    if (-not (Test-Path "$root\frontend\build\index.html")) {
        Write-Host 'UI not built yet - running npm run build...' -ForegroundColor Yellow
        Push-Location "$root\frontend"; npm run build; Pop-Location
    }
    if ($Open) { $flags += '--open' }
    Push-Location "$root\backend"
    try { uv run python -m extrahorizon @flags } finally { Pop-Location }
    exit $LASTEXITCODE
}

$backendCmd = "Set-Location '$root\backend'; uv run python -m extrahorizon $($flags -join ' ')"
Start-Process powershell -ArgumentList '-NoExit', '-Command', $backendCmd | Out-Null
Write-Host "Backend starting in a new window on :$Port ..." -ForegroundColor Cyan
$env:EH_BACKEND = "http://127.0.0.1:$Port"
Push-Location "$root\frontend"
try { npm run dev } finally { Pop-Location }
