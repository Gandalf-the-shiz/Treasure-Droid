# Intraday learning pulse: live predictions, reasoning, daytrade (every 4h on weekdays).
param([int]$IntervalHours = 4)

$ErrorActionPreference = "Continue"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
Set-Location $RepoRoot

$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

while ($true) {
    $dow = (Get-Date).DayOfWeek.ToString()
    if (@("Monday", "Tuesday", "Wednesday", "Thursday", "Friday") -contains $dow) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $log = Join-Path $LogDir "intraday-$stamp.log"
        & $Python "scripts/learning_harness.py" "--once" "--mode" "intraday" *>&1 | Tee-Object -FilePath $log
    }
    Start-Sleep -Seconds ([Math]::Max($IntervalHours, 1) * 3600)
}
