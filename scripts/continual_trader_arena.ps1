# 100-trader arena pulse — compare strategy genomes hourly.
param([int]$IntervalHours = 1)

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
$env:PYTHONPATH = Join-Path $RepoRoot "scripts"

while ($true) {
    & $Python (Join-Path $ScriptRoot "intelligence\trader_arena.py") --pulse --version active
    Start-Sleep -Seconds ([Math]::Max(1, $IntervalHours) * 3600)
}
