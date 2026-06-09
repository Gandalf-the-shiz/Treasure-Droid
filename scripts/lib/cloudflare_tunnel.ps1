# Shared Cloudflare tunnel helpers (quick + named).
$script:CloudflareTunnelLibLoaded = $true

function Get-NostraRepoRoot {
    param([string]$ScriptPath = $MyInvocation.PSCommandPath)
    Split-Path -Parent (Split-Path -Parent $ScriptPath)
}

function Get-CloudflaredExe {
    $cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
    if ($cf) { return $cf }
    $win = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
    if (Test-Path $win) { return $win }
    return $null
}

function Get-CloudflareConfig {
    param([string]$RepoRoot)
    $path = Join-Path $RepoRoot "config\cloudflare.json"
    if (-not (Test-Path $path)) { return $null }
    try {
        return (Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Test-NamedTunnelReady {
    param($Cfg, [string]$RepoRoot)
    if (-not $Cfg) { return $false }
    if (($Cfg.mode -ne "named") -and ($Cfg.mode -ne "Named")) { return $false }
    $tunnelHost = ($Cfg.hostname -as [string]).Trim()
    if (-not $tunnelHost -or $tunnelHost -match 'YOUR_DOMAIN') { return $false }
    $rel = ($Cfg.configPath -as [string]).Trim()
    if (-not $rel) { $rel = "data/cloudflare/config.yml" }
    $yml = Join-Path $RepoRoot ($rel -replace '/', '\')
    return (Test-Path $yml)
}

function Get-NamedTunnelPublicUrl {
    param($Cfg)
    $tunnelHost = ($Cfg.hostname -as [string]).Trim().TrimEnd('/')
    if (-not $tunnelHost) { return $null }
    if ($tunnelHost -notmatch '^https?://') { return "https://$tunnelHost" }
    return $tunnelHost.TrimEnd('/')
}

function Get-PythonExe {
    $candidates = @(
        "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe",
        "python"
    )
    foreach ($p in $candidates) {
        if ($p -eq "python" -or (Test-Path $p)) { return $p }
    }
    return "python"
}

function Publish-TunnelUrl {
    param(
        [string]$RepoRoot,
        [string]$PublicUrl,
        [switch]$RefreshMegamind
    )
    if (-not $PublicUrl) { return }
    $url = $PublicUrl.Trim().TrimEnd('/')
    $urlFile = Join-Path $RepoRoot "data\intelligence\megamind\tunnel_url.txt"
    New-Item -ItemType Directory -Force -Path (Split-Path $urlFile) | Out-Null
    Set-Content -Path $urlFile -Value $url -Encoding UTF8

    $megaPath = Join-Path $RepoRoot "config\megamind.json"
    if (Test-Path $megaPath) {
        try {
            $py = Get-PythonExe
            $patch = @"
import json
from pathlib import Path
p = Path(r'$megaPath')
d = json.loads(p.read_text(encoding='utf-8-sig'))
d['publicDashboardUrl'] = '$url'
p.write_text(json.dumps(d, indent=2) + '\n', encoding='utf-8')
"@
            & $py -c $patch 2>$null | Out-Null
        } catch { }
    }

    if ($RefreshMegamind) {
        $py = Get-PythonExe
        Set-Location $RepoRoot
        $env:PYTHONPATH = Join-Path $RepoRoot "scripts"
        & $py scripts/intelligence/megamind.py --refresh-urls 2>&1 | Out-Null
    }
}

function Start-CloudflareQuickTunnel {
    param(
        [string]$CfExe,
        [int]$Port = 8000,
        [string]$LogFile
    )
    if (Test-Path $LogFile) { Remove-Item $LogFile -Force -ErrorAction SilentlyContinue }
    $proc = Start-Process -FilePath $CfExe -ArgumentList @(
        "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$Port"
    ) -RedirectStandardError $LogFile -PassThru -WindowStyle Hidden
    return $proc
}

function Wait-QuickTunnelUrl {
    param([string]$LogFile, [int]$MaxSeconds = 180)
    for ($i = 0; $i -lt ($MaxSeconds / 2); $i++) {
        Start-Sleep -Seconds 2
        if (-not (Test-Path $LogFile)) { continue }
        $text = Get-Content $LogFile -Raw -ErrorAction SilentlyContinue
        if ($text -match '(https://[a-z0-9-]+\.trycloudflare\.com)') {
            return $Matches[1]
        }
    }
    return $null
}

function Start-CloudflareNamedTunnel {
    param(
        [string]$CfExe,
        [string]$ConfigYml,
        [string]$LogFile
    )
    if (Test-Path $LogFile) { Remove-Item $LogFile -Force -ErrorAction SilentlyContinue }
    $proc = Start-Process -FilePath $CfExe -ArgumentList @(
        "tunnel", "--no-autoupdate", "--config", $ConfigYml, "run"
    ) -RedirectStandardError $LogFile -PassThru -WindowStyle Hidden
    return $proc
}

function Get-OriginCertPath {
    $home = $env:USERPROFILE
    @(
        (Join-Path $home ".cloudflared\cert.pem"),
        (Join-Path $home "cloudflared\cert.pem")
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}
