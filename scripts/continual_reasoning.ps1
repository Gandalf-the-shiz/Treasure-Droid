# Light tick: reasoning agent paper portfolio + journal (every 15 min).
param([int]$TickMinutes = 15)

$ErrorActionPreference = "Continue"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
Set-Location $RepoRoot

$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

while ($true) {
    & $Python "scripts/reasoning_agent.py" "--tick" 2>&1 | Out-Null
    Start-Sleep -Seconds ([Math]::Max($TickMinutes, 5) * 60)
}
