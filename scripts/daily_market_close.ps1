# Post-close intelligence refresh (no email). Called by nostradamus-live daily_update.ps1
# or run manually after market close. Does NOT respawn arena genomes (preserves experiment).
$ErrorActionPreference = "Continue"
$RepoRoot = "c:\Users\nicho\Nostradamus_remote_audit"
$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "scripts"
$env:PREFER_NPU = "true"
$env:UNIFIED_SCORE_ENABLED = "true"
$env:ALLOW_SHORTS = "true"
if (-not $env:SEC_USER_AGENT) {
    $env:SEC_USER_AGENT = "NostradamusResearch contact@example.com"
}

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$log = Join-Path $LogDir ("daily-close-update-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))

function Log($msg) { "$((Get-Date).ToString('s'))  $msg" | Tee-Object -FilePath $log -Append }

function Step($label, $script, $scriptArgs = @()) {
    Log "[close] $label"
    & $Python $script @scriptArgs 2>&1 | ForEach-Object { Log "  $_" }
}

Log "[close] Nostradamus post-close update start"

$fetch = Join-Path $RepoRoot "scripts\fetch-history.py"
if (Test-Path $fetch) {
    Log "[close] incremental price history (max 25 min)"
    $job = Start-Job -ScriptBlock {
        param($Py, $Path, $Root)
        Set-Location $Root
        & $Py $Path 2>&1
    } -ArgumentList $Python, $fetch, $RepoRoot
    $done = Wait-Job $job -Timeout 1500
    if ($done) {
        Receive-Job $job *>&1 | ForEach-Object { Log "  $_" }
        Remove-Job $job -Force
    } else {
        Stop-Job $job -Force
        Remove-Job $job -Force
        Log "[close] fetch-history timed out; continuing"
    }
}

Step "Live ML panel" "scripts\generate_live_predictions.py"
Step "Finnhub feed (PEAD+revisions)" "scripts\fetch_finnhub.py"
Step "Sentiment feed (news+reddit gossip)" "scripts\fetch_sentiment_feed.py"
Step "Alpha engine (market-neutral book)" "scripts\intelligence\alpha\engine.py"
Step "Fleet — crew walks forward (paper)" "scripts\intelligence\fleet\run.py"
Step "Alpaca paper rebalance" "scripts\intelligence\alpha\alpaca_executor.py" @("--execute")
Step "NPU status" "scripts\npu_runtime.py"
Step "Congress trades" "scripts\fetch-congress-trades.py"
$insLimit = if ($env:INSIDER_FETCH_LIMIT) { $env:INSIDER_FETCH_LIMIT } else { "80" }
Step "Insider trades" "scripts\fetch-insider-trades.py" @("--limit", $insLimit)
Step "Mass psychology" "scripts\intelligence\mass_psychology.py"
Step "Insider monitor" "scripts\intelligence\insider_monitor.py"
Step "Execution feedback" "scripts\intelligence\execution_feedback.py"
Step "Forward IC" "scripts\intelligence\forward_score.py"
Step "Alpha IC measure" "scripts\intelligence\alpha\measure.py"
Step "Per-sleeve IC + ICIR weights" "scripts\intelligence\alpha\sleeve_ic.py"
Step "Mad Scientist Lab (walk-forward)" "scripts\intelligence\historical\walkforward_lab.py" @("--genomes", "200", "--promote", "2")
Step "Champion sync" "scripts\intelligence\champion_sync.py"
Step "Arena consolidate" "scripts\intelligence\trader_arena.py" @("--consolidate")
Step "Investor Arena pulse (active)" "scripts\intelligence\trader_arena.py" @("--migrate", "--pulse", "--version", "active", "--traders", "100")
Step "Arena harvest+evolve" "scripts\intelligence\trader_arena.py" @("--harvest-evolve")
Step "Treasure Droid (captain) tick" "scripts\intelligence\megamind.py" @("--tick")
Step "Intelligence brain" "scripts\intelligence\brain.py"
Step "Trade manifests" "scripts\generate_trade_signals.py"

Log "[close] Penny Wolf scan"
$pennyScript = Join-Path $RepoRoot "scripts\_daily_penny_scan.py"
@'
import sys
sys.path.insert(0, "scripts")
from penny_engine import scan_universe
print(f"scanned {len(scan_universe(limit=300))} candidates")
'@ | Set-Content -Path $pennyScript -Encoding UTF8
& $Python $pennyScript 2>&1 | ForEach-Object { Log "  $_" }
Remove-Item $pennyScript -ErrorAction SilentlyContinue

$mode = "daily"
if ((Get-Date).DayOfWeek.ToString() -eq "Sunday") { $mode = "weekly" }
Log "[close] learning harness ($mode)"
& $Python "scripts\learning_harness.py" "--once" "--mode" $mode 2>&1 | ForEach-Object { Log "  $_" }

Log "[close] done"
