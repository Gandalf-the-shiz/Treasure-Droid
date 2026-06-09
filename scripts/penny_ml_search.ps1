# Penny Wolf ML search - long-lived supervisor; batches trials to limit memory spikes.
param(
    [int]$BatchTrials = 20,
    [int]$CooldownSec = 15,
    [int]$ErrorCooldownSec = 120
)

$ErrorActionPreference = "Continue"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
$Paused     = Join-Path $RepoRoot "data\PAUSED.txt"
$LogDir     = Join-Path $RepoRoot "logs"
$log        = Join-Path $LogDir "penny-ml-search.log"
$LockFile   = Join-Path $RepoRoot "data\penny\ml\search.lock"

$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

New-Item -ItemType Directory -Force -Path $LogDir, (Split-Path $LockFile) | Out-Null
$env:PYTHONPATH = Join-Path $RepoRoot "scripts"

function Log($m) {
    $line = "$((Get-Date).ToString('s'))  $m"
    $line | Tee-Object -FilePath $log -Append
}

# Prevent duplicate search processes from autonomous_loop restarts.
if (Test-Path $LockFile) {
    try {
        $old = Get-Process -Id (Get-Content $LockFile -ErrorAction Stop) -ErrorAction Stop
        if ($old -and -not $old.HasExited) {
            Log "[penny-ml] already running (PID $($old.Id)); exiting duplicate wrapper"
            exit 0
        }
    } catch { }
}
Set-Content -Path $LockFile -Value $PID -Encoding UTF8

Log "[penny-ml] supervisor online (batch=$BatchTrials trials, PID $PID)"

try {
    while ($true) {
        if (Test-Path $Paused) {
            Start-Sleep -Seconds 300
            continue
        }
        Set-Location (Join-Path $RepoRoot "scripts")
        Log "[penny-ml] starting batch ($BatchTrials trials)"
        & $Python "-m" "penny_ml.search" "--trials" $BatchTrials 2>&1 | ForEach-Object { Log $_ }
        $code = $LASTEXITCODE
        if ($code -ne 0) {
            Log "[penny-ml] batch exit code $code - sleeping ${ErrorCooldownSec}s"
            Start-Sleep -Seconds $ErrorCooldownSec
        } else {
            Start-Sleep -Seconds $CooldownSec
        }
    }
} finally {
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
}
