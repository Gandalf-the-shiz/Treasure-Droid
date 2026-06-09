# Running Nostradamus locally — forever

This document describes how to "productionize" Nostradamus for personal,
always-on use on a single Windows machine. There is no cloud, no containers,
and no admin privileges required.

## One-time setup

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-local.ps1
```

That script is idempotent. It will:

1. Verify the Python 3.11 (arm64) interpreter and required packages.
2. Create `logs/`, `data/historical/`, `data/sentiment/`, `data/investor_v3/`, `models/v3/investor/`.
3. Register a **server task** ("Nostradamus Local Server") that auto-starts
   the FastAPI server at your logon and restarts it within a minute if it
   crashes (up to 999 times).
4. Register a **nightly task** ("Nostradamus Nightly Retrain") that runs the
   full pipeline at **17:30 local, Monday–Friday**.
5. Start the server immediately and smoke-test `GET /api/health`.
6. Print a status summary including current model + data freshness.

Open the dashboard:

- UI:               http://127.0.0.1:4174/
- Pipeline status:  http://127.0.0.1:4174/api/status
- Health (+ job):   http://127.0.0.1:4174/api/health

## The nightly "always learning" loop

`scripts/nightly.ps1` runs three steps and rotates logs:

1. `fetch-history.py`  — incremental 5-day refresh from yfinance into
   `data/historical/<sector>.json`. Failures are non-fatal so training still
   runs on whatever bars are on disk.
2. `train-investor-v3.py` — retrains the policy with the canonical config.
3. `enrich_decisions.py --last-days 10` — attaches FinBERT sentiment to the
   most recent decisions.

Each step writes a marker to the log (`# fetch exit code: 0`, etc.) which the
server parses for `/api/status` and the Command Center "Pipeline" badge.

The last 30 `nightly-*.log` files are kept; older ones are pruned on each run.

## Manual operations

```powershell
# Start the server now without rebooting:
Start-ScheduledTask -TaskName "Nostradamus Local Server"

# Trigger a one-off nightly run:
Start-ScheduledTask -TaskName "Nostradamus Nightly Retrain"

# Inspect scheduled tasks:
Get-ScheduledTask | Where-Object { $_.TaskName -match "Nostradamus" }

# Tail the latest nightly log:
Get-Content (Get-ChildItem logs\nightly-*.log | Sort LastWriteTime | Select -Last 1) -Tail 40 -Wait

# Remove everything:
Unregister-ScheduledTask -TaskName "Nostradamus Local Server"  -Confirm:$false
Unregister-ScheduledTask -TaskName "Nostradamus Nightly Retrain" -Confirm:$false
```

## Where things live

| Resource              | Path                                       |
|-----------------------|--------------------------------------------|
| Server logs           | `logs/server-*.log` (uvicorn)              |
| Nightly logs          | `logs/nightly-YYYYMMDD-HHmmss.log`         |
| Decisions JSON        | `data/investor_v3/decisions.json`          |
| Trained policy        | `models/v3/investor/policy.joblib`         |
| FinBERT cache         | `data/sentiment/per_symbol.json`           |
| Sector bar files      | `data/historical/<sector>.json`            |
| Bars manifest         | `data/historical/manifest.json`            |
