# Mad Scientist 24/7 - endless historical genome experiments + champion promotion.
param(
    [int]$SleepMinutes = 180,
    [int]$ErrorCooldownSec = 300
)

$ErrorActionPreference = "Continue"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
$Paused     = Join-Path $RepoRoot "data\PAUSED.txt"
$LogDir     = Join-Path $RepoRoot "logs"
$log        = Join-Path $LogDir "mad-scientist-loop.log"
$LockFile   = Join-Path $RepoRoot "data\intelligence\historical\loop.lock"

$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

New-Item -ItemType Directory -Force -Path $LogDir, (Split-Path $LockFile) | Out-Null
$env:PYTHONPATH = Join-Path $RepoRoot "scripts"

function Log($m) {
    $line = "$((Get-Date).ToString('s'))  $m"
    $line | Tee-Object -FilePath $log -Append
}

if (Test-Path $LockFile) {
    try {
        $old = Get-Process -Id (Get-Content $LockFile -ErrorAction Stop) -ErrorAction Stop
        if ($old -and -not $old.HasExited) {
            Log "[mad-scientist] already running (PID $($old.Id)); exiting duplicate"
            exit 0
        }
    } catch { }
}
Set-Content -Path $LockFile -Value $PID -Encoding UTF8

Log "[mad-scientist] 24/7 loop online (sleep=${SleepMinutes}m, PID $PID)"

while ($true) {
    if (Test-Path $Paused) {
        Log "[mad-scientist] PAUSED.txt present - sleeping 10m"
        Start-Sleep -Seconds 600
        continue
    }
    try {
        Log "[mad-scientist] cycle start"
        & $Python "scripts\intelligence\historical\mad_scientist_loop.py" "--once" 2>&1 | ForEach-Object { Log "  $_" }
        Log "[mad-scientist] cycle done; sleeping ${SleepMinutes}m"
        Start-Sleep -Seconds ([Math]::Max(60, $SleepMinutes * 60))
    } catch {
        Log "[mad-scientist] error: $_"
        Start-Sleep -Seconds $ErrorCooldownSec
    }
}
