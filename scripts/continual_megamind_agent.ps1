# Watches Megamind approved queue and runs Cursor SDK agent when API key is configured.
param([int]$IntervalMinutes = 5)

$ErrorActionPreference = "Continue"
$RepoRoot = "c:\Users\nicho\Nostradamus_remote_audit"
$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
$SdkPy = Join-Path $RepoRoot "tools\python311-amd64\python.exe"
if (-not (Test-Path $SdkPy)) {
    $ensure = Join-Path $RepoRoot "scripts\ensure_megamind_sdk_python.ps1"
    if (Test-Path $ensure) {
        try { & powershell -NoProfile -ExecutionPolicy Bypass -File $ensure } catch { Log "[megamind-agent] sdk python install failed: $_" }
    }
}
if (Test-Path $SdkPy) { $Python = $SdkPy }

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$log = Join-Path $LogDir "continual-megamind-agent.log"

function Log($m) { "$((Get-Date).ToString('s'))  $m" | Tee-Object -FilePath $log -Append }

Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "scripts"

Log "[megamind-agent] watcher online (${IntervalMinutes}m)"

while ($true) {
    $pending = Join-Path $RepoRoot "data\intelligence\megamind\pending_for_agent.json"
    if (Test-Path $pending) {
        try {
            $doc = Get-Content $pending -Raw | ConvertFrom-Json
            if ($doc.sdkCompletedAt -and $doc.postCompletionAt) {
                Log "[megamind-agent] task complete (SDK + post-completion)"
            } elseif ($doc.sdkCompletedAt) {
                Log "[megamind-agent] running post-completion (debug + email)..."
                & $Python "scripts\intelligence\megamind_post_completion.py" 2>&1 | ForEach-Object { Log "  $_" }
            } else {
                Log "[megamind-agent] running SDK worker..."
                & $Python "scripts\intelligence\megamind_run_agent.py" 2>&1 | ForEach-Object { Log "  $_" }
            }
        } catch {
            Log "[megamind-agent] error: $_"
        }
    }
    Start-Sleep -Seconds ([Math]::Max(60, $IntervalMinutes * 60))
}
