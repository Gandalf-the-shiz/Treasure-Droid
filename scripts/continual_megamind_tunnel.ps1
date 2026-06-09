# Keep Cloudflare tunnel alive (named config.yml or quick trycloudflare fallback).
param([int]$Port = 8000)

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $RepoRoot "scripts\lib\cloudflare_tunnel.ps1")

$LogDir = Join-Path $RepoRoot "logs"
$LogFile = Join-Path $LogDir "cloudflared-megamind.log"
$loopLog = Join-Path $LogDir "continual-megamind-tunnel.log"
$CfExe = Get-CloudflaredExe

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Log($m) { "$((Get-Date).ToString('s'))  $m" | Tee-Object -FilePath $loopLog -Append }

$proc = $null
Log "[tunnel] watcher online (port $Port)"

while ($true) {
    $cfg = Get-CloudflareConfig -RepoRoot $RepoRoot
    if ($cfg -and $cfg.localPort) { $Port = [int]$cfg.localPort }
    $useNamed = Test-NamedTunnelReady -Cfg $cfg -RepoRoot $RepoRoot

    if (-not $CfExe) {
        $CfExe = Get-CloudflaredExe
        if (-not $CfExe) {
            Log "[tunnel] cloudflared missing - install winget Cloudflare.cloudflared"
            Start-Sleep 300
            continue
        }
    }

    if (-not $proc -or $proc.HasExited) {
        if ($proc -and $proc.HasExited) { Log "[tunnel] cloudflared exited; restarting" }

        if ($useNamed) {
            $ymlRel = ($cfg.configPath -as [string]).Trim()
            if (-not $ymlRel) { $ymlRel = "data/cloudflare/config.yml" }
            $ymlPath = Join-Path $RepoRoot ($ymlRel -replace '/', '\')
            $publicUrl = Get-NamedTunnelPublicUrl -Cfg $cfg
            $proc = Start-CloudflareNamedTunnel -CfExe $CfExe -ConfigYml $ymlPath -LogFile $LogFile
            Log "[tunnel] named PID $($proc.Id) -> $publicUrl"
            Publish-TunnelUrl -RepoRoot $RepoRoot -PublicUrl $publicUrl -RefreshMegamind
        } else {
            $proc = Start-CloudflareQuickTunnel -CfExe $CfExe -Port $Port -LogFile $LogFile
            Log "[tunnel] quick PID $($proc.Id)"
            Start-Sleep 8
            $url = Wait-QuickTunnelUrl -LogFile $LogFile -MaxSeconds 120
            if ($url) {
                Log "[tunnel] quick URL $url"
                Publish-TunnelUrl -RepoRoot $RepoRoot -PublicUrl $url -RefreshMegamind
            }
        }
    } elseif ($useNamed) {
        $publicUrl = Get-NamedTunnelPublicUrl -Cfg $cfg
        Publish-TunnelUrl -RepoRoot $RepoRoot -PublicUrl $publicUrl
    } else {
        $url = $null
        if (Test-Path $LogFile) {
            $text = Get-Content $LogFile -Raw -ErrorAction SilentlyContinue
            if ($text -match '(https://[a-z0-9-]+\.trycloudflare\.com)') { $url = $Matches[1] }
        }
        if ($url) { Publish-TunnelUrl -RepoRoot $RepoRoot -PublicUrl $url }
    }

    Start-Sleep 30
}
