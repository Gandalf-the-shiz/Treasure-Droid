# One-time setup: register a Windows Scheduled Task that runs scripts/nightly.ps1
# every weekday at 17:30 local time (after US market close).
#
# Usage (run once, normal user — no admin needed):
#     powershell -ExecutionPolicy Bypass -File scripts\register-nightly-task.ps1
#
# To remove:
#     Unregister-ScheduledTask -TaskName "Nostradamus Nightly Retrain" -Confirm:$false

$ErrorActionPreference = "Stop"

$TaskName  = "Nostradamus Nightly Retrain"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$Nightly   = Join-Path $ScriptDir "nightly.ps1"

if (-not (Test-Path $Nightly)) {
    Write-Error "Cannot find $Nightly"
    exit 2
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Nightly`"" `
    -WorkingDirectory $RepoRoot

# Weekdays 17:30 local
$Trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At 5:30PM

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

# Register under current user, no stored password (interactive).
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $Action `
    -Trigger  $Trigger `
    -Settings $Settings `
    -Description "Regenerate data/investor_v3/decisions.json after US market close." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' (weekdays 17:30 local)." -ForegroundColor Green
Write-Host "Inspect with: Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "Run now with: Start-ScheduledTask -TaskName '$TaskName'"
