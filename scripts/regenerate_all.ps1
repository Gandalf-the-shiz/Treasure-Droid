# Regenerate intelligence artifacts, arena pulse, manifests, and Penny scan.
# Daily automation uses daily_market_close.ps1 (pulse only, keeps genomes).
# Pass -RespawnArena to reset all 200 arena genomes (manual / rare).
param([switch]$RespawnArena)
$ErrorActionPreference = "Continue"
$NostraRoot = "c:\Users\nicho\Nostradamus_remote_audit"
$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

Set-Location $NostraRoot
$env:PYTHONPATH = Join-Path $NostraRoot "scripts"
$env:PREFER_NPU = "true"
$env:UNIFIED_SCORE_ENABLED = "true"
$env:ALLOW_SHORTS = "true"

function Step($label, $script, $scriptArgs = @()) {
    Write-Host "[regen] $label"
    & $Python $script @scriptArgs 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        Write-Host "  (exit $LASTEXITCODE - continuing)"
    }
}

Step "NPU status" "scripts\npu_runtime.py"
Step "Congress trades" "scripts\fetch-congress-trades.py"
# 80 tickers keeps regen under ~5 min; raise INSIDER_FETCH_LIMIT env for full sweep
$insLimit = if ($env:INSIDER_FETCH_LIMIT) { $env:INSIDER_FETCH_LIMIT } else { "80" }
Step "Insider trades" "scripts\fetch-insider-trades.py" @("--limit", $insLimit)
Step "Mass psychology" "scripts\intelligence\mass_psychology.py"
Step "Insider monitor" "scripts\intelligence\insider_monitor.py"
Step "Execution feedback" "scripts\intelligence\execution_feedback.py"
Step "Forward IC" "scripts\intelligence\forward_score.py"
Step "Champion sync" "scripts\intelligence\champion_sync.py"
$arenaArgs = @("--migrate", "--pulse", "--version", "all", "--traders", "100")
if ($RespawnArena) { $arenaArgs = @("--migrate", "--respawn") + $arenaArgs }
Step "Trader arena v1+v2" "scripts\intelligence\trader_arena.py" $arenaArgs
Step "Intelligence brain" "scripts\intelligence\brain.py"
Step "Trade manifests" "scripts\generate_trade_signals.py"

Write-Host "[regen] Penny Wolf scan"
$pennyScript = Join-Path $NostraRoot "scripts\_regen_penny_scan.py"
@'
import sys
sys.path.insert(0, "scripts")
from penny_engine import scan_universe
n = len(scan_universe(limit=300))
print(f"scanned {n} candidates")
'@ | Set-Content -Path $pennyScript -Encoding UTF8
& $Python $pennyScript 2>&1 | ForEach-Object { Write-Host "  $_" }
Remove-Item $pennyScript -ErrorAction SilentlyContinue

Write-Host "[regen] done"
