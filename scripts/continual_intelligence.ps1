# Intelligence pulse every 2 hours — mass psychology + insider monitor + feedback loop.
param([int]$IntervalHours = 2)

$ErrorActionPreference = "Continue"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
$env:PYTHONPATH = Join-Path $RepoRoot "scripts"

Write-Host "[intelligence] pulse every ${IntervalHours}h"
while ($true) {
    & $Python (Join-Path $ScriptRoot "intelligence\brain.py")
    Start-Sleep -Seconds ([Math]::Max(1, $IntervalHours) * 3600)
}
