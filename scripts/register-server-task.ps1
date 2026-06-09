# scripts/register-server-task.ps1
#
# Registers a scheduled task that auto-starts the Nostradamus local FastAPI
# server (`scripts/serve.py`) at user logon. The task restarts the server up
# to 999 times if it crashes, so it is effectively always-on while you are
# logged in.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\register-server-task.ps1
#
# Remove:
#   Unregister-ScheduledTask -TaskName "Nostradamus Local Server" -Confirm:$false

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
$Python     = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
$Port       = 4174
$TaskName   = "Nostradamus Local Server"

if (-not (Test-Path $Python)) {
    Write-Error "Python not found at $Python"
    exit 2
}

# Action: run uvicorn-hosted FastAPI bound to 127.0.0.1
$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "scripts\serve.py --host 127.0.0.1 --port $Port" `
    -WorkingDirectory $RepoRoot

# Trigger: at logon of the current user
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:UserName

# Settings: restart on failure, no execution time limit, hidden window
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew `
    -Hidden

# Principal: current interactive user, run only when logged on
$principal = New-ScheduledTaskPrincipal -UserId $env:UserName -LogonType Interactive -RunLevel Limited

# Unregister any prior instance so re-running is idempotent
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Nostradamus local FastAPI server (autostart, restart on crash)." | Out-Null

Write-Host "[ok] Registered scheduled task: $TaskName"
Write-Host "     trigger : at user logon ($env:UserName)"
Write-Host "     cmd     : $Python scripts\serve.py --port $Port"
Write-Host "     cwd     : $RepoRoot"
Write-Host ""
Write-Host "Start now without waiting for next logon:"
Write-Host "  Start-ScheduledTask -TaskName `"$TaskName`""
