# Lightweight autonomous improvement loop (feeds + signals + arena) while you are away.
param([int]$IntervalHours = 6)

$ErrorActionPreference = "Continue"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$log = Join-Path $LogDir "continual-improve.log"

function Log($m) { "$((Get-Date).ToString('s'))  $m" | Tee-Object -FilePath $log -Append }

Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "scripts"
$env:UNIFIED_SCORE_ENABLED = "true"
$env:ALLOW_SHORTS = "true"
$env:PREFER_NPU = "true"
if (-not $env:SEC_USER_AGENT) {
    $env:SEC_USER_AGENT = "NostradamusResearch contact@example.com"
}

Log "[improve] online every ${IntervalHours}h"

while ($true) {
    Log "[improve] cycle start"
    & $Python "scripts\fetch-congress-trades.py" 2>&1 | ForEach-Object { Log "  $_" }
    $insLimit = if ($env:INSIDER_FETCH_LIMIT) { $env:INSIDER_FETCH_LIMIT } else { "60" }
    & $Python "scripts\fetch-insider-trades.py" --limit $insLimit 2>&1 | ForEach-Object { Log "  $_" }
    & $Python "scripts\intelligence\brain.py" 2>&1 | ForEach-Object { Log "  $_" }
    & $Python "scripts\intelligence\trader_arena.py" --pulse --version active 2>&1 | ForEach-Object { Log "  $_" }
    & $Python "scripts\intelligence\trader_arena.py" --harvest-evolve 2>&1 | ForEach-Object { Log "  $_" }
    & $Python "scripts\intelligence\megamind.py" --tick 2>&1 | ForEach-Object { Log "  $_" }
    & $Python "scripts\generate_trade_signals.py" 2>&1 | ForEach-Object { Log "  $_" }
    & $Python "scripts\intelligence\forward_score.py" 2>&1 | ForEach-Object { Log "  $_" }
    Log "[improve] cycle done; sleeping ${IntervalHours}h"
    Start-Sleep -Seconds ([Math]::Max(1, $IntervalHours) * 3600)
}
