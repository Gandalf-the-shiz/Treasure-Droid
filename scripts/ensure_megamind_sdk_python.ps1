# Install local x64 Python for cursor-sdk on Windows ARM64 hosts (SDK has no win-arm64 wheel).
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Dest = Join-Path $RepoRoot "tools\python311-amd64"
$Py = Join-Path $Dest "python.exe"
if (Test-Path $Py) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Py -c "import os; assert hasattr(os, 'get_blocking'); import cursor_sdk" 2>$null | Out-Null
    $ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prev
    if ($ok) {
        Write-Host "[sdk-python] already installed at $Py"
        exit 0
    }
    Write-Host "[sdk-python] repairing incomplete install at $Dest"
    Remove-Item -Recurse -Force $Dest -ErrorAction SilentlyContinue
}

# cursor-sdk on Windows needs os.get_blocking (added for pipes in 3.12+).
$Ver = "3.12.10"
$ExeUrl = "https://www.python.org/ftp/python/$Ver/python-$Ver-amd64.exe"
$ExePath = Join-Path $env:TEMP "python-$Ver-amd64.exe"

Write-Host "[sdk-python] downloading Python $Ver installer (amd64)..."
Invoke-WebRequest -Uri $ExeUrl -OutFile $ExePath -UseBasicParsing
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

Write-Host "[sdk-python] installing to $Dest (quiet)..."
$installArgs = @(
    "/quiet", "InstallAllUsers=0", "PrependPath=0", "Include_test=0", "Include_doc=0",
    "Include_launcher=0", "TargetDir=$Dest", "REBOOT=ReallySuppress"
)
Start-Process -FilePath $ExePath -ArgumentList $installArgs -Wait -NoNewWindow

if (-not (Test-Path $Py)) {
    throw "Python install failed: $Py not found"
}

Write-Host "[sdk-python] installing cursor-sdk..."
& $Py -m pip install -q --only-binary=cursor-sdk cursor-sdk

Write-Host "[sdk-python] ready: $Py"
