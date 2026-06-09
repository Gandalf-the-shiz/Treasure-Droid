# Nostradamus Continuous Brain - market-aware multi-tier learning loop.
# Replaces fixed 24h harness with intraday pulses + daily close + weekly deep train.

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
Set-Location $RepoRoot

$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Host "[brain] continuous scheduler started - Ctrl+C to stop"
while ($true) {
    & $Python "scripts/learning_scheduler.py" --tick
    $schedPath = Join-Path $RepoRoot "data\learning\schedule.json"
    $sleepSec = 1800
    if (Test-Path $schedPath) {
        $sched = Get-Content $schedPath -Raw | ConvertFrom-Json
        if ($sched.sleepSeconds) { $sleepSec = [int]$sched.sleepSeconds }
        $mode = $sched.recommendedMode
        $sess = $sched.session
        Write-Host "[brain] mode=$mode session=$sess sleep=$sleepSec"
    }
    Start-Sleep -Seconds $sleepSec
}
