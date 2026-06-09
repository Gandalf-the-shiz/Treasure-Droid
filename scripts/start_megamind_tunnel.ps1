# Expose local serve.py for phone / remote (Cloudflare named or quick tunnel).
param([int]$Port = 8000)

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $RepoRoot "scripts\lib\cloudflare_tunnel.ps1")

$LogDir = Join-Path $RepoRoot "logs"
$LogFile = Join-Path $LogDir "cloudflared-megamind.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$CfExe = Get-CloudflaredExe
if (-not $CfExe) {
    Write-Host "[tunnel] cloudflared not found. Install: winget install --id Cloudflare.cloudflared"
    exit 1
}

$cfg = Get-CloudflareConfig -RepoRoot $RepoRoot
$useNamed = Test-NamedTunnelReady -Cfg $cfg -RepoRoot $RepoRoot
if ($cfg -and $cfg.localPort) { $Port = [int]$cfg.localPort }

if ($useNamed) {
    $ymlRel = ($cfg.configPath -as [string]).Trim()
    if (-not $ymlRel) { $ymlRel = "data/cloudflare/config.yml" }
    $ymlPath = Join-Path $RepoRoot ($ymlRel -replace '/', '\')
    $publicUrl = Get-NamedTunnelPublicUrl -Cfg $cfg
    Write-Host "[tunnel] named -> $ymlPath (port $Port)"
    $proc = Start-CloudflareNamedTunnel -CfExe $CfExe -ConfigYml $ymlPath -LogFile $LogFile
    Publish-TunnelUrl -RepoRoot $RepoRoot -PublicUrl $publicUrl -RefreshMegamind
    Write-Host "[tunnel] public URL: $publicUrl"
} else {
    Write-Host "[tunnel] quick -> http://127.0.0.1:$Port"
    $proc = Start-CloudflareQuickTunnel -CfExe $CfExe -Port $Port -LogFile $LogFile
    $publicUrl = Wait-QuickTunnelUrl -LogFile $LogFile
    if (-not $publicUrl) {
        Write-Host "[tunnel] timed out — check $LogFile"
        Write-Host "[tunnel] For a stable URL: .\scripts\setup_cloudflare_tunnel.ps1"
        exit 1
    }
    Publish-TunnelUrl -RepoRoot $RepoRoot -PublicUrl $publicUrl -RefreshMegamind
    Write-Host "[tunnel] public URL: $publicUrl"
}

Write-Host "[tunnel] running PID $($proc.Id). Ctrl+C stops this window only."
while (-not $proc.HasExited) { Start-Sleep -Seconds 30 }
