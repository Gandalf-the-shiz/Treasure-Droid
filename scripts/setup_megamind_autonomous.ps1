# One-time Megamind autonomous setup: config, secrets template, SDK, scheduled watcher, user env.
param(
    [string]$CursorApiKey = "",
    [switch]$PersistUserEnv
)

$ErrorActionPreference = "Stop"
$RepoRoot = "c:\Users\nicho\Nostradamus_remote_audit"
$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

Set-Location $RepoRoot

Write-Host "[setup] installing cursor-sdk (x64 embed on ARM hosts)..."
$ensureSdk = Join-Path $RepoRoot "scripts\ensure_megamind_sdk_python.ps1"
if (Test-Path $ensureSdk) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $ensureSdk
    $sdkPy = Join-Path $RepoRoot "tools\python311-amd64\python.exe"
    if (Test-Path $sdkPy) { $Python = $sdkPy }
}
& $Python -m pip install -q --only-binary=cursor-sdk cursor-sdk 2>$null
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install -q cursor-sdk
}

$configPath = Join-Path $RepoRoot "config\megamind.json"
$secretsPath = Join-Path $RepoRoot "config\megamind.secrets.json"
$exampleSecrets = Join-Path $RepoRoot "config\megamind.secrets.example.json"

$config = @{
    approveSecret = (Get-Content $configPath -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json).approveSecret
    dashboardBaseUrl = "http://127.0.0.1:8000"
    autoLaunch = "both"
    autoApproveEnabled = $true
    autoApprovePriorities = @("critical", "high")
    cursorModel = "composer-2.5"
    sdkBlocking = $false
}
if (-not $config.approveSecret) {
    $config.approveSecret = -join ((48..57) + (97..102) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
}
& $Python -c @"
import json
from pathlib import Path
p = Path(r'$configPath')
doc = {
    'approveSecret': '$($config.approveSecret)',
    'dashboardBaseUrl': 'http://127.0.0.1:8000',
    'autoLaunch': 'both',
    'autoApproveEnabled': True,
    'autoApprovePriorities': ['critical', 'high'],
    'cursorModel': 'composer-2.5',
    'sdkBlocking': False,
}
p.write_text(json.dumps(doc, indent=2), encoding='utf-8')
"@
Write-Host "[setup] wrote config/megamind.json (autoApprove high/critical, autoLaunch both)"

if (-not (Test-Path $secretsPath)) {
    Copy-Item $exampleSecrets $secretsPath
    Write-Host "[setup] created config/megamind.secrets.json - add your Cursor API key"
}

if ($CursorApiKey) {
    & $Python -c @"
import json
from pathlib import Path
p = Path(r'$secretsPath')
doc = json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else {}
doc['cursorApiKey'] = '$CursorApiKey'
p.write_text(json.dumps(doc, indent=2), encoding='utf-8')
"@
    Write-Host "[setup] stored API key in megamind.secrets.json"
    if ($PersistUserEnv) {
        [Environment]::SetEnvironmentVariable("CURSOR_API_KEY", $CursorApiKey, "User")
        Write-Host "[setup] persisted CURSOR_API_KEY to user environment"
    }
}

# Register watcher task (optional, alongside autonomous_loop)
$taskName = "NostradamusMegamindAgent"
$script = Join-Path $RepoRoot "scripts\continual_megamind_agent.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -IntervalMinutes 5" `
    -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    Write-Host "[setup] registered scheduled task: $taskName (at logon)"
} catch {
    Write-Host "[setup] scheduled task skipped (need admin or use autonomous_loop.ps1): $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Done. Remaining step if SDK agent did not run yet:"
Write-Host "  1. Get API key: https://cursor.com/dashboard/integrations"
Write-Host "  2. Paste into config/megamind.secrets.json as cursorApiKey"
Write-Host "  3. Or re-run setup with -CursorApiKey and -PersistUserEnv"
Write-Host ""
Write-Host "Autonomous behavior:"
Write-Host "  - Daily 5pm: Megamind tick auto-approves critical/high recs and launches Cursor"
Write-Host "  - Watcher: runs SDK agent on approved queue every 5 min when key is set"
