# Startup shortcuts: Nostradamus UI learning + optional PMP learning.
$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
$startup = [Environment]::GetFolderPath("Startup")

$uiLoop = Join-Path $ScriptRoot "autonomous_loop.ps1"
$uiCmd = Join-Path $startup "nostradamus_ui_autonomous.cmd"
@(
    "@echo off",
    "start """" /min powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$uiLoop`""
) | Set-Content -Path $uiCmd -Encoding ASCII
Write-Host "Installed UI learning: $uiCmd"

$pmpSetup = "C:\Users\nicho\prediction-market-predictor\scripts\setup_autonomous.ps1"
if (Test-Path $pmpSetup) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $pmpSetup
}

Write-Host ""
Write-Host "Also ensure nostradamus-live search loop is running (nostradamus_autonomous.cmd in Startup)."
