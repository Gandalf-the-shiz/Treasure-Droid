# Daily close learning: feeds refresh + investor path (weekdays ~5pm via supervisor).
$ErrorActionPreference = "Continue"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
Set-Location $RepoRoot

$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$log = Join-Path $LogDir ("daily-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))

$mode = "daily"
if ((Get-Date).DayOfWeek.ToString() -eq "Sunday") { $mode = "weekly" }

& $Python "scripts/learning_harness.py" "--once" "--mode" $mode *>&1 | Tee-Object -FilePath $log
