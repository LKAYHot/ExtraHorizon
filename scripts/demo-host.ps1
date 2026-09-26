# ExtraHorizon - host the remote demo on this PC, with an HTTPS tunnel (Cloudflare Tunnel) in front.
# The browser on the laptop only captures and plays; face analysis, speech detection and all the
# API calls run here. Guide: docs/REMOTE_DEMO.md
#
#   .\scripts\demo-host.ps1 -PublicUrl https://demo.example.com   first run: remember the public URL
#   .\scripts\demo-host.ps1              serve on 127.0.0.1:8080 for the tunnel; restart if it stops
#   .\scripts\demo-host.ps1 -Check       is everything ready? (server, tunnel, public URL, key, sleep)
#   .\scripts\demo-host.ps1 -ShowKey     print the access key here (type it on the laptop)
#   .\scripts\demo-host.ps1 -NewKey      replace the access key (every browser must enter the new one)
#   .\scripts\demo-host.ps1 -Install     start the demo host automatically at logon (scheduled task)
#   .\scripts\demo-host.ps1 -Uninstall   remove that task
#   Options: -Port 8080  -MockLLM  -MockVoice  -Quiet (server output to logs\ instead of the console)
param(
    [switch]$Check, [switch]$ShowKey, [switch]$NewKey, [switch]$Install, [switch]$Uninstall,
    [int]$Port = 8080, [string]$PublicUrl = '', [switch]$MockLLM, [switch]$MockVoice, [switch]$Quiet
)
$ErrorActionPreference = 'Continue'  # native tools print warnings on stderr; results are checked explicitly
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root '.env'
$logDir = Join-Path $root 'logs'
$taskName = 'ExtraHorizon demo host'

function Say([string]$text, [string]$color = 'Gray') { Write-Host $text -ForegroundColor $color }
function Ok([string]$text) { Say "  [ok]   $text" 'Green' }
function Warn([string]$text) { Say "  [warn] $text" 'Yellow' }
function Bad([string]$text) { Say "  [FAIL] $text" 'Red' }

# ------------------------------------------------------------------ .env (git-ignored, secret-guarded)
function Get-EnvValue([string]$name) {
    if (-not (Test-Path -LiteralPath $envFile)) { return '' }
    foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
        if ($line -match "^\s*$name\s*=\s*(.*)$") { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return ''
}

function Set-EnvValue([string]$name, [string]$value) {
    $lines = @()
    if (Test-Path -LiteralPath $envFile) { $lines = @(Get-Content -LiteralPath $envFile -Encoding UTF8) }
    $found = $false
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($line in $lines) {
        if ($line -match "^\s*$name\s*=") { $out.Add("$name=$value"); $found = $true } else { $out.Add($line) }
    }
    if (-not $found) { $out.Add("$name=$value") }
    [System.IO.File]::WriteAllLines($envFile, $out.ToArray(), (New-Object System.Text.UTF8Encoding($false)))
}

function New-AccessKey {
    # 6 groups of 4 from an unambiguous alphabet (no 0/O, 1/l/I): ~139 bits, easy to type on a laptop
    $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $chars = New-Object System.Collections.Generic.List[char]
    $buf = New-Object byte[] 1
    while ($chars.Count -lt 24) {
        $rng.GetBytes($buf)
        if ($buf[0] -lt 224) { $chars.Add($alphabet[$buf[0] % 56]) }  # 224 = 4 x 56: no modulo bias
    }
    $groups = for ($i = 0; $i -lt 24; $i += 4) { -join $chars.GetRange($i, 4) }
    return ($groups -join '-')
}

function Get-PublicUrl {
    if ($PublicUrl) {
        $u = $PublicUrl.Trim().TrimEnd('/')
        if ($u -notmatch '^https?://[^/]+$') { Bad "-PublicUrl must look like https://demo.example.com"; exit 2 }
        if ((Get-EnvValue 'EH_PUBLIC_URL') -ne $u) { Set-EnvValue 'EH_PUBLIC_URL' $u; Say "Saved EH_PUBLIC_URL=$u in .env" 'Cyan' }
        return $u
    }
    return (Get-EnvValue 'EH_PUBLIC_URL')
}

function Confirm-Key {
    if ((Get-EnvValue 'EH_ACCESS_KEY').Length -lt 12) {
        Set-EnvValue 'EH_ACCESS_KEY' (New-AccessKey)
        Say 'Created an access key in .env - see it with: .\scripts\demo-host.ps1 -ShowKey' 'Cyan'
    }
}

# ------------------------------------------------------------------ checks
function Test-Server {
    try {
        $h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 5
        Ok "server on 127.0.0.1:$Port - LLM $($h.llm.model) configured=$($h.llm.configured), voice $($h.tts.state), vision available=$($h.vision.available)"
        return $true
    } catch {
        Bad "nothing answers on 127.0.0.1:$Port - start it: .\scripts\demo-host.ps1"
        return $false
    }
}

function Test-TunnelService {
    $svc = Get-Service -Name 'cloudflared' -ErrorAction SilentlyContinue
    if (-not $svc) { Warn 'no cloudflared Windows service - is the tunnel running some other way?'; return }
    if ($svc.Status -eq 'Running') { Ok "cloudflared service running (start type: $($svc.StartType))" }
    else { Bad "cloudflared service is $($svc.Status) - start it: Start-Service cloudflared (as administrator)" }
    if ($svc.StartType -ne 'Automatic') { Warn 'cloudflared does not start automatically with Windows' }
}

function Test-Public([string]$url) {
    if (-not $url) { Warn 'no public URL yet - run once with -PublicUrl https://your-demo.example.com'; return }
    $hostName = ([Uri]$url).Host
    $public = @()
    foreach ($server in '1.1.1.1', '8.8.8.8') {
        try {
            $public = @(Resolve-DnsName -Name $hostName -Server $server -Type A -ErrorAction Stop |
                Where-Object { $_.IPAddress } | Select-Object -ExpandProperty IPAddress)
            if ($public.Count) { break }
        } catch { }
    }
    if (-not $public.Count) { Bad "public DNS has no address for $hostName yet"; return }
    $ip = $public[0]
    try {
        $mine = @(Resolve-DnsName -Name $hostName -Type A -ErrorAction Stop | Where-Object { $_.IPAddress } |
            Select-Object -ExpandProperty IPAddress)
        if (-not ($mine | Where-Object { $public -contains $_ })) {
            Warn "this PC's DNS gives $hostName = $($mine -join ', ') but public DNS gives $($public -join ', ')"
            # ask the configured DNS servers directly (bypasses the Windows cache): who is stale?
            $upstreamStale = $false
            $servers = @(Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                ForEach-Object { $_.ServerAddresses } | Select-Object -Unique)
            foreach ($srv in $servers) {
                $a = @(Resolve-DnsName -Name $hostName -Type A -Server $srv -DnsOnly -ErrorAction SilentlyContinue |
                    Where-Object { $_.IPAddress } | Select-Object -ExpandProperty IPAddress)
                if ($a.Count -and -not ($a | Where-Object { $public -contains $_ })) { $upstreamStale = $true }
            }
            if (-not $upstreamStale) {
                Say  '         only the Windows cache is stale: ipconfig /flushdns' 'Yellow'
            } else {
                Say  '         your DNS server (usually the ISP) still has the OLD records - browsers on this network show' 'Yellow'
                Say  '         ERR_SSL_VERSION_OR_CIPHER_MISMATCH. Turn on Secure DNS (DNS-over-HTTPS, Cloudflare) in the browser,' 'Yellow'
                Say  '         or set this PC''s DNS to 1.1.1.1, or wait until that cache expires (docs/REMOTE_DEMO.md).' 'Yellow'
            }
        }
    } catch { }
    $tlsPort = if (([Uri]$url).Scheme -eq 'https') { 443 } else { 80 }  # (PowerShell names ignore case: not $port)
    $raw = & curl.exe -s -m 20 --resolve "${hostName}:${tlsPort}:$ip" "$url/api/access" -w "`n%{http_code}" 2>$null
    $lines = @($raw -split "`n")
    $code = $lines[-1].Trim()
    $body = ($lines[0..([Math]::Max(0, $lines.Count - 2))] -join "`n")
    if ($code -eq '200') {
        $a = $body | ConvertFrom-Json
        if ($a.configured -and $a.required) { Ok "$url answers through $($a.transport) and asks for the access key" }
        elseif (-not $a.configured) { Bad "$url answers, but remote access is off (no EH_ACCESS_KEY on the server)" }
        else { Warn "$url answers but does not look remote ($($a.transport)) - check the tunnel headers" }
    } elseif ($code -eq '502') { Bad "$url -> 502: the tunnel is up but nothing answers on its origin (start the demo host; the tunnel should point to http://127.0.0.1:$Port)" }
    elseif ($code -eq '530') { Bad "$url -> 530: Cloudflare cannot reach the tunnel (is cloudflared running and connected?)" }
    else { Bad "$url -> HTTP $code" }
}

function Test-Sleep {
    # the output is localized; its last two hex values are the current AC and DC indexes
    $hex = @(& powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 2>$null |
        Where-Object { $_ -match '0x([0-9a-fA-F]{8})\s*$' } | ForEach-Object { $Matches[1] })
    if ($hex.Count -ge 2) {
        $sec = [Convert]::ToInt32($hex[$hex.Count - 2], 16)
        if ($sec -eq 0) { Ok 'the PC never sleeps on AC power' }
        else {
            Warn ("the PC sleeps after {0} min on AC power when idle - the demo host keeps it awake while it runs;" -f [int]($sec / 60))
            Say  '         to be sure, switch sleep off yourself: powercfg /change standby-timeout-ac 0' 'Yellow'
        }
    }
}

# ------------------------------------------------------------------ actions
if ($ShowKey) {
    $k = Get-EnvValue 'EH_ACCESS_KEY'
    if (-not $k) { Warn 'no access key yet - start the demo host once, or run with -NewKey'; exit 1 }
    Say "Access key: $k" 'Cyan'
    exit 0
}

if ($NewKey) {
    Set-EnvValue 'EH_ACCESS_KEY' (New-AccessKey)
    Say 'New access key saved in .env - every browser has to enter it again. Restart the demo host, then: -ShowKey' 'Cyan'
    exit 0
}

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Ok "removed the scheduled task '$taskName'"
    } else { Say "no scheduled task '$taskName'" }
    exit 0
}

$url = Get-PublicUrl

if ($Install) {
    if (-not $url) { Bad 'set the public URL first: .\scripts\demo-host.ps1 -PublicUrl https://your-demo.example.com -Install'; exit 2 }
    Confirm-Key
    $argsLine = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`" -Quiet -Port $Port"
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argsLine -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force `
        -Description "ExtraHorizon remote demo on 127.0.0.1:$Port (behind the tunnel for $url). Logs: $logDir" | Out-Null
    Ok "the demo host now starts when $env:USERNAME logs on (task '$taskName', output in logs\)"
    Say "Start it now without logging off: Start-ScheduledTask -TaskName '$taskName'" 'Cyan'
    exit 0
}

if ($Check) {
    Say "ExtraHorizon demo host - check" 'Cyan'
    $up = Test-Server
    Test-TunnelService
    Test-Public $url
    if ((Get-EnvValue 'EH_ACCESS_KEY').Length -ge 12) { Ok 'access key is set in .env (see it with -ShowKey)' }
    else { Bad 'no access key in .env - the demo host creates one on its first start' }
    Test-Sleep
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { Ok "autostart at logon is installed ('$taskName')" }
    else { Say "  [info] no autostart - install it with: .\scripts\demo-host.ps1 -Install" }
    if ($up) { exit 0 } else { exit 1 }
}

# ------------------------------------------------------------------ serve
if (-not $url) {
    Bad 'tell the demo host its public URL once: .\scripts\demo-host.ps1 -PublicUrl https://your-demo.example.com'
    exit 2
}
Confirm-Key

$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($busy) {
    $who = (Get-Process -Id $busy.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    Bad "port $Port is already in use by $who (pid $($busy.OwningProcess)) - stop it, or use -Port and point the tunnel there"
    exit 1
}

# the UI served to the laptop: rebuild when the sources are newer than the build
$index = Join-Path $root 'frontend\build\index.html'
$newest = Get-ChildItem -Path (Join-Path $root 'frontend\src') -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not (Test-Path $index) -or ($newest -and $newest.LastWriteTime -gt (Get-Item $index).LastWriteTime)) {
    Say 'Building the UI (npm run build)...' 'Yellow'
    Push-Location (Join-Path $root 'frontend')
    try { npm run build | Out-Host } finally { Pop-Location }
}

# keep the PC awake while the demo host runs (released automatically when it stops)
try {
    Add-Type -Namespace ExtraHorizon -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);' -ErrorAction Stop
    [ExtraHorizon.Power]::SetThreadExecutionState([uint32]2147483649) | Out-Null  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
} catch { Warn 'could not ask Windows to stay awake - check the sleep settings (-Check)' }

$env:EH_HOST = '127.0.0.1'  # only the tunnel on this PC reaches it
$env:EH_PORT = "$Port"
$env:EH_PUBLIC_URL = $url
$flags = @()
if ($MockLLM) { $flags += '--mock-llm' }
if ($MockVoice) { $flags += '--mock-voice' }
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

Say ''
Say "  ExtraHorizon demo host" 'Cyan'
Say "  local   http://127.0.0.1:$Port   (this PC - no key needed)"
Say "  public  $url   (Cloudflare Tunnel -> http://127.0.0.1:$Port, access key required)"
Say "  key     .\scripts\demo-host.ps1 -ShowKey      check: .\scripts\demo-host.ps1 -Check"
Say "  Ctrl+C stops it." 'DarkGray'
Say ''

$delay = 2
while ($true) {
    $started = Get-Date
    if ($Quiet) {
        foreach ($f in 'demo-host.out.log', 'demo-host.err.log') {
            $p = Join-Path $logDir $f
            if (Test-Path $p) { Move-Item -Force $p ($p -replace '\.log$', '.prev.log') }
        }
        $argList = @('run', '--directory', (Join-Path $root 'backend'), 'python', '-m', 'extrahorizon') + $flags
        $proc = Start-Process -FilePath 'uv' -ArgumentList $argList -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput (Join-Path $logDir 'demo-host.out.log') -RedirectStandardError (Join-Path $logDir 'demo-host.err.log')
        $code = $proc.ExitCode
    } else {
        Push-Location (Join-Path $root 'backend')
        try { uv run python -m extrahorizon @flags } finally { Pop-Location }
        $code = $LASTEXITCODE
    }
    $ran = ((Get-Date) - $started).TotalSeconds
    if ($ran -gt 120) { $delay = 2 } else { $delay = [Math]::Min(60, $delay * 2) }
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path (Join-Path $logDir 'demo-host.events.log') -Value "$stamp server stopped (exit $code) after $([int]$ran) s; restart in $delay s"
    Warn "server stopped (exit $code) - restarting in $delay s (Ctrl+C to quit)"
    Start-Sleep -Seconds $delay
}
