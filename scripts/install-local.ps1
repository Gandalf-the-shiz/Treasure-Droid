# scripts/install-local.ps1
#
# One-shot bootstrap that "productionizes" Nostradamus for personal use on
# this Windows machine. Idempotent — safe to re-run after pulling new code.
#
# What it does:
#   1. Verify Python interpreter + pip deps.
#   2. Create required data/log directories.
#   3. Register the local FastAPI server as a logon-triggered scheduled task.
#   4. Register the nightly retrain + enrich pipeline (M–F at 17:30 local).
#   5. Start the server immediately if not already running.
#   6. Smoke-test /api/health and print a status summary.
#
# Usage (Run as your normal user, NOT admin):
#   powershell -ExecutionPolicy Bypass -File scripts\install-local.ps1

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
$Python     = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
$Port       = 4174
Set-Location $RepoRoot

Write-Host "================================================================"
Write-Host "  Nostradamus local production bootstrap"
Write-Host "================================================================"
Write-Host ""

# 1. Python interpreter
Write-Host "[1/6] checking Python..."
if (-not (Test-Path $Python)) {
    Write-Error "Python not found at $Python. Install Python 3.11 (arm64) and retry."
    exit 2
}
$pyVer = & $Python --version 2>&1
Write-Host "      $pyVer"

# 2. Verify critical packages without forcing a full install (those are heavy).
Write-Host "[2/6] verifying packages (fastapi, uvicorn, yfinance, onnxruntime)..."
$check = & $Python -c "import importlib.util as u; mods=['fastapi','uvicorn','yfinance','onnxruntime','joblib','numpy','pandas']; missing=[m for m in mods if not u.find_spec(m)]; print('OK' if not missing else 'MISSING:'+','.join(missing))" 2>&1
Write-Host "      $check"
if ($check -match "MISSING") {
    Write-Warning "Some packages are missing. Run: $Python -m pip install -r scripts\requirements.txt"
}

# 3. Required directories
Write-Host "[3/6] ensuring directories exist..."
$dirs = @("logs", "data\historical", "data\sentiment", "data\investor_v3", "models\v3\investor")
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot $d) | Out-Null
    Write-Host "      $d"
}

# 4. Server scheduled task
Write-Host "[4/6] registering server scheduled task..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptRoot "register-server-task.ps1")
if ($LASTEXITCODE -ne 0) { Write-Warning "register-server-task.ps1 returned $LASTEXITCODE" }

# 5. Nightly retrain scheduled task
Write-Host "[5/6] registering nightly retrain task..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptRoot "register-nightly-task.ps1")
if ($LASTEXITCODE -ne 0) { Write-Warning "register-nightly-task.ps1 returned $LASTEXITCODE" }

# 6. Start the server now + smoke test
Write-Host "[6/6] starting server and smoke-testing /api/health..."
try { Start-ScheduledTask -TaskName "Nostradamus Local Server" -ErrorAction Stop } catch { Write-Warning $_ }

$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}

Write-Host ""
Write-Host "================================================================"
if ($ok) {
    Write-Host "  [OK] Nostradamus is productionized."
    Write-Host "================================================================"
    Write-Host ""
    Write-Host "  Open the dashboard:   http://127.0.0.1:$Port/"
    Write-Host "  Pipeline status:      http://127.0.0.1:$Port/api/status"
    $h = (Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing).Content | ConvertFrom-Json
    Write-Host ""
    Write-Host "  Current state:"
    Write-Host "    version           : $($h.version)"
    Write-Host "    decisions exists  : $($h.decisions.exists)"
    Write-Host "    last bar date     : $($h.pipeline.last_bar_date)"
    if ($h.pipeline.last_nightly.exists) {
        Write-Host "    last nightly      : $($h.pipeline.last_nightly.path)"
        Write-Host "                        fetch=$($h.pipeline.last_nightly.fetch_rc) train=$($h.pipeline.last_nightly.train_rc) enrich=$($h.pipeline.last_nightly.enrich_rc)"
    } else {
        Write-Host "    last nightly      : (never run \u2014 will run M\u2013F at 17:30 local)"
    }
    Write-Host ""
    Write-Host "  Scheduled tasks:"
    Get-ScheduledTask | Where-Object { $_.TaskName -match "Nostradamus" } |
        ForEach-Object { Write-Host ("    - {0,-32} state={1}" -f $_.TaskName, $_.State) }
} else {
    Write-Host "  [WARN] Server did not respond on http://127.0.0.1:$Port within 10s."
    Write-Host "================================================================"
    Write-Host "  Check the task in Task Scheduler and the latest logs/retrain-*.log."
}
Write-Host ""
