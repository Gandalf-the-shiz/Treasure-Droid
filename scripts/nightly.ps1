# Runs train-investor-v3.py with the canonical config and logs to logs/nightly-<date>.log.
# Designed to be called by Windows Task Scheduler. Exits non-zero on failure so
# the scheduler can mark the run as failed.

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
Set-Location $RepoRoot

$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Python not found at $Python"
    exit 2
}

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp  = Get-Date -Format "yyyyMMdd-HHmmss"
$LogFile = Join-Path $LogDir "nightly-$Stamp.log"

$Args = @(
    "scripts/train-investor-v3.py",
    "--top-k", "5",
    "--max-position-frac", "0.20",
    "--max-gross-exposure", "0.90",
    "--kelly-scale", "0.5",
    "--cost-bps", "5",
    "--slippage-bps", "10",
    "--min-proba", "0.60",
    "--min-pred-ret", "0.020",
    "--min-price", "5",
    "--min-adv", "1000000",
    "--min-vol-20", "0.01",
    "--max-daily-ret", "0.20",
    "--policy-mode", "edge"
)

"# nostradamus nightly retrain @ $(Get-Date -Format o)" | Out-File -FilePath $LogFile -Encoding utf8
"# cmd: $Python $($Args -join ' ')"                    | Out-File -FilePath $LogFile -Encoding utf8 -Append

# Step 1/3 — refresh OHLCV bars (incremental 5-day pull by default).
"# fetch-history @ $(Get-Date -Format o)" | Out-File -FilePath $LogFile -Encoding utf8 -Append
& $Python "scripts/fetch-history.py" *>> $LogFile
$fetchRc = $LASTEXITCODE
"# fetch exit code: $fetchRc" | Out-File -FilePath $LogFile -Encoding utf8 -Append

# Fallback: if the yfinance fetcher failed badly (e.g. Yahoo rate-limit or block),
# try the Stooq-fallback multiyear fetcher with a small 1-year window. This is
# slower but uses a different upstream, so it survives Yahoo outages.
if ($fetchRc -ne 0) {
    "# fetch fallback (multiyear+stooq) @ $(Get-Date -Format o)" | Out-File -FilePath $LogFile -Encoding utf8 -Append
    & $Python "scripts/fetch-history-multiyear.py" "--years" "1" *>> $LogFile
    $fallbackRc = $LASTEXITCODE
    "# fetch fallback exit code: $fallbackRc" | Out-File -FilePath $LogFile -Encoding utf8 -Append
}
# Fetch failures are non-fatal — we still want to retrain on whatever bars we have.

# Step 2/3 — retrain the investor policy.
"# train @ $(Get-Date -Format o)" | Out-File -FilePath $LogFile -Encoding utf8 -Append
& $Python @Args *>> $LogFile
$rc = $LASTEXITCODE
"# train exit code: $rc" | Out-File -FilePath $LogFile -Encoding utf8 -Append

# Prefer full autonomous harness (data + train + promote + enrich + signals).
# Set NOSTRADAMUS_USE_HARNESS=0 to use legacy investor-only path below.
$useHarness = $env:NOSTRADAMUS_USE_HARNESS -ne "0"
if ($useHarness) {
    "# learning-harness @ $(Get-Date -Format o)" | Out-File -FilePath $LogFile -Encoding utf8 -Append
    & $Python "scripts/learning_harness.py" "--once" "--skip-predictor" *>> $LogFile
    $rc = $LASTEXITCODE
    "# harness exit code: $rc" | Out-File -FilePath $LogFile -Encoding utf8 -Append
} else {
    "# fetch-congress @ $(Get-Date -Format o)" | Out-File -FilePath $LogFile -Encoding utf8 -Append
    & $Python "scripts/fetch-congress-trades.py" *>> $LogFile
    if ($rc -eq 0) {
        & $Python "scripts/fetch-macro.py" *>> $LogFile
        & $Python "scripts/fetch-regime-data.py" *>> $LogFile
    }
    if ($rc -eq 0) {
        & $Python "scripts/enrich_decisions.py" "--last-days" "10" *>> $LogFile
        & $Python "scripts/enrich_congress_decisions.py" "--last-days" "30" *>> $LogFile
        & $Python "scripts/generate_trade_signals.py" *>> $LogFile
    }
}

# Log rotation — keep the 30 most recent nightly-*.log files.
try {
    Get-ChildItem -Path $LogDir -Filter "nightly-*.log" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip 30 |
        Remove-Item -Force -ErrorAction SilentlyContinue
} catch { }

"# pipeline finished @ $(Get-Date -Format o)" | Out-File -FilePath $LogFile -Encoding utf8 -Append
exit $rc
