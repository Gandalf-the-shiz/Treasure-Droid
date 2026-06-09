# Penny Wolf desk pulse — sub-$5 scan + paper trades every N hours.
param([int]$IntervalHours = 2)

$ErrorActionPreference = "Continue"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
Set-Location $RepoRoot

$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

while ($true) {
    if (Test-Path (Join-Path $RepoRoot "data\PAUSED.txt")) {
        Start-Sleep -Seconds 300
        continue
    }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $log = Join-Path $LogDir "penny-wolf-$stamp.log"
    & $Python "scripts\penny_engine.py" tick *>&1 | Tee-Object -FilePath $log
    Start-Sleep -Seconds ([Math]::Max($IntervalHours, 1) * 3600)
}
