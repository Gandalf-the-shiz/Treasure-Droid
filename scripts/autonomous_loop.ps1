# Nostradamus UI repo - always-on learning supervisor (no admin).
#   - mad-scientist historical lab every 3h (24/7 genome experiments)
#   - reasoning tick every 15 min
#   - intraday harness every 4h (weekdays)
#   - post-close refresh: nostradamus-live daily_update.ps1 at 5:00 PM Eastern (not duplicated here)
# Also run nostradamus-live's supervisor separately for ML search + paper gate.

$ErrorActionPreference = "Continue"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
Set-Location $RepoRoot

$reasonScript  = Join-Path $ScriptRoot "continual_reasoning.ps1"
$intradayScript = Join-Path $ScriptRoot "continual_intraday.ps1"
$pennyScript   = Join-Path $ScriptRoot "continual_penny.ps1"
$pennyMlScript = Join-Path $ScriptRoot "penny_ml_search.ps1"
$intelScript   = Join-Path $ScriptRoot "continual_intelligence.ps1"
$arenaScript   = Join-Path $ScriptRoot "continual_trader_arena.ps1"
$improveScript = Join-Path $ScriptRoot "continual_improve.ps1"
$madScientistScript = Join-Path $ScriptRoot "continual_mad_scientist.ps1"
$megamindAgentScript = Join-Path $ScriptRoot "continual_megamind_agent.ps1"
$megamindTunnelScript = Join-Path $ScriptRoot "continual_megamind_tunnel.ps1"
$tunnelEnabled = $false
$cfgPath = Join-Path $RepoRoot "config\megamind.json"
if (Test-Path $cfgPath) {
    try {
        $tunnelEnabled = (& python -c "import json;from pathlib import Path;p=Path(r'$cfgPath');d=json.loads(p.read_text(encoding='utf-8-sig'));print('1' if d.get('tunnelEnabled') else '0')" 2>$null) -eq '1'
    } catch { $tunnelEnabled = $false }
}

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$loopLog = Join-Path $LogDir "autonomous_loop.log"
$markerDir = Join-Path $LogDir "state"
New-Item -ItemType Directory -Force -Path $markerDir | Out-Null

function Log($m) { "$((Get-Date).ToString('s'))  $m" | Tee-Object -FilePath $loopLog -Append }

function Start-Child($label, $file, [string[]]$extra) {
    Log "[loop] starting $label"
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$file`"") + $extra
    return Start-Process powershell -ArgumentList $args -WindowStyle Hidden -PassThru
}

Log "[loop] Nostradamus autonomous supervisor online"
$reason  = Start-Child "reasoning"  $reasonScript  @("-TickMinutes", "15")
$intraday = Start-Child "intraday" $intradayScript @("-IntervalHours", "4")
$penny    = Start-Child "penny"    $pennyScript   @("-IntervalHours", "2")
$pennyMl  = Start-Child "penny-ml" $pennyMlScript @()
$intel    = Start-Child "intelligence" $intelScript @("-IntervalHours", "2")
$arena    = Start-Child "trader-arena" $arenaScript @("-IntervalHours", "1")
$improve  = Start-Child "improve"    $improveScript @("-IntervalHours", "6")
$madScientist = Start-Child "mad-scientist" $madScientistScript @("-SleepMinutes", "180")
$megamindAgent = Start-Child "megamind-agent" $megamindAgentScript @("-IntervalMinutes", "5")
$megamindTunnel = $null
if ($tunnelEnabled) {
    $megamindTunnel = Start-Child "megamind-tunnel" $megamindTunnelScript @()
    Log "[loop] Cloudflare tunnel enabled for remote Megamind approve"
}

while ($true) {
    if ($reason.HasExited)  { Log "[loop] reasoning died; restarting";  $reason  = Start-Child "reasoning"  $reasonScript  @("-TickMinutes", "15") }
    if ($intraday.HasExited) { Log "[loop] intraday died; restarting"; $intraday = Start-Child "intraday" $intradayScript @("-IntervalHours", "4") }
    if ($penny.HasExited)    { Log "[loop] penny wolf died; restarting"; $penny    = Start-Child "penny"    $pennyScript   @("-IntervalHours", "2") }
    if ($pennyMl.HasExited) {
        $lock = Join-Path $RepoRoot "data\penny\ml\search.lock"
        $skip = $false
        if (Test-Path $lock) {
            try {
                $pidMl = [int](Get-Content $lock -Raw).Trim()
                $p = Get-Process -Id $pidMl -ErrorAction Stop
                if ($p -and -not $p.HasExited) { $skip = $true }
            } catch { }
        }
        if (-not $skip) {
            Log "[loop] penny ML search died; restarting"
            $pennyMl = Start-Child "penny-ml" $pennyMlScript @()
        }
    }
    if ($intel.HasExited)    { Log "[loop] intelligence pulse died; restarting"; $intel = Start-Child "intelligence" $intelScript @("-IntervalHours", "2") }
    if ($arena.HasExited)    { Log "[loop] trader arena died; restarting"; $arena = Start-Child "trader-arena" $arenaScript @("-IntervalHours", "1") }
    if ($improve.HasExited)  { Log "[loop] improve loop died; restarting"; $improve = Start-Child "improve" $improveScript @("-IntervalHours", "6") }
    if ($madScientist.HasExited) {
        $msLock = Join-Path $RepoRoot "data\intelligence\historical\loop.lock"
        $skipMs = $false
        if (Test-Path $msLock) {
            try {
                $pidMs = [int](Get-Content $msLock -Raw).Trim()
                $p = Get-Process -Id $pidMs -ErrorAction Stop
                if ($p -and -not $p.HasExited) { $skipMs = $true }
            } catch { }
        }
        if (-not $skipMs) {
            Log "[loop] mad-scientist died; restarting"
            $madScientist = Start-Child "mad-scientist" $madScientistScript @("-SleepMinutes", "180")
        }
    }
    if ($megamindAgent.HasExited) { Log "[loop] megamind SDK watcher died; restarting"; $megamindAgent = Start-Child "megamind-agent" $megamindAgentScript @("-IntervalMinutes", "5") }
    if ($tunnelEnabled -and $megamindTunnel -and $megamindTunnel.HasExited) {
        Log "[loop] megamind tunnel died; restarting"
        $megamindTunnel = Start-Child "megamind-tunnel" $megamindTunnelScript @()
    }

    Start-Sleep -Seconds 60
}
