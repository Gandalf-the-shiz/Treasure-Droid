# Phone / remote Megamind approve: set public URL for email links.
param(
    [ValidateSet("Lan", "Tunnel", "Url", "")]
    [string]$Mode = "",
    [string]$PublicUrl = "",
    [switch]$RefreshOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ConfigPath = Join-Path $RepoRoot "config\megamind.json"
$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

function Update-MegamindConfig([hashtable]$Fields) {
    $py = @"
import json
from pathlib import Path
p = Path(r'$ConfigPath')
doc = json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else {}
doc.update(json.loads('''$($Fields | ConvertTo-Json -Compress)'''))
p.write_text(json.dumps(doc, indent=2), encoding='utf-8')
print('[setup] publicDashboardUrl =', doc.get('publicDashboardUrl'))
"@
    & $Python -c $py
}

function Refresh-Urls {
    Set-Location $RepoRoot
    $env:PYTHONPATH = Join-Path $RepoRoot "scripts"
    & $Python scripts/intelligence/megamind.py --refresh-urls
}

if ($RefreshOnly) {
    Refresh-Urls
    exit 0
}

if ($Mode -eq "Url" -or $PublicUrl) {
    if (-not $PublicUrl) { throw "Use -PublicUrl https://your-host" }
    Update-MegamindConfig @{ publicDashboardUrl = $PublicUrl.TrimEnd('/') }
}
elseif ($Mode -eq "Lan") {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.IPAddress -match '^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)'
    } | Select-Object -First 1).IPAddress
    if (-not $ip) { throw "No LAN IPv4 found" }
    $url = "http://${ip}:8000"
    Update-MegamindConfig @{
        publicDashboardUrl = $url
        serveHost = "0.0.0.0"
        remoteApproveEnabled = $true
    }
    Write-Host "[setup] LAN approve URL: $url"
    Write-Host "[setup] Phone on same Wi-Fi. Restart: .\scripts\reboot_systems.ps1"
    Write-Host "[setup] Allow Windows Firewall for Python on private networks if prompted."
}
elseif ($Mode -eq "Tunnel") {
    Update-MegamindConfig @{ tunnelEnabled = $true; remoteApproveEnabled = $true }
    Write-Host "[setup] Starting Cloudflare tunnel in a new window..."
    Start-Process powershell -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $RepoRoot "scripts\start_megamind_tunnel.ps1")
    ) -WorkingDirectory $RepoRoot
    Write-Host "[setup] When URL appears, run: .\scripts\setup_remote_megamind_approve.ps1 -RefreshOnly"
    exit 0
}
else {
    Write-Host @"

Remote Megamind approve (email link on your phone)
=================================================

Approve links look like:  {base}/api/megamind/approve/{id}?token=...
If base is http://127.0.0.1:8000, your phone cannot reach it.

  A) Same Wi-Fi (home)
     .\scripts\setup_remote_megamind_approve.ps1 -Mode Lan
     .\scripts\reboot_systems.ps1

  B) Anywhere (cellular) — Cloudflare quick tunnel
     winget install Cloudflare.cloudflared
     .\scripts\setup_remote_megamind_approve.ps1 -Mode Tunnel

  C) Your HTTPS host (Tailscale Funnel, ngrok, fixed domain)
     .\scripts\setup_remote_megamind_approve.ps1 -Mode Url -PublicUrl https://YOUR_HOST

Refresh links after URL changes:
     .\scripts\setup_remote_megamind_approve.ps1 -RefreshOnly

Needs: PC on, serve.py on :8000, tunnel running for mode B.

"@
    exit 0
}

Refresh-Urls
