# Reboot Nostradamus + PMP servers and autonomous learning loops.
$ErrorActionPreference = "Continue"
$NostraRoot = "c:\Users\nicho\Nostradamus_remote_audit"
$PmpRoot    = "c:\Users\nicho\prediction-market-predictor"
$LiveRoot   = "c:\Users\nicho\nostradamus-live"
$Python     = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

function Stop-Port($port) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

$regenScript = Join-Path $NostraRoot "scripts\regenerate_all.ps1"
$skipRegen = $env:SKIP_REGEN -eq "1"
if ((Test-Path $regenScript) -and -not $skipRegen) {
    Write-Host "[reboot] full regeneration..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $regenScript
} elseif ($skipRegen) {
    Write-Host "[reboot] SKIP_REGEN=1 - services only"
}

Write-Host "[reboot] stopping listeners 8000/8001/4174..."
Stop-Port 8000
Stop-Port 8001
Stop-Port 4174
Start-Sleep -Seconds 2

$env:PYTHONPATH = Join-Path $NostraRoot "scripts"
$env:PREFER_NPU = "true"
$env:ALLOW_SHORTS = "true"

$serveHost = "127.0.0.1"
$cfgPath = Join-Path $NostraRoot "config\megamind.json"
if (Test-Path $cfgPath) {
    try {
        $serveHost = & $Python -c "import json;from pathlib import Path;p=Path(r'$cfgPath');d=json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else {};print(d.get('serveHost') or '127.0.0.1')" 2>$null
        if (-not $serveHost) { $serveHost = "127.0.0.1" }
    } catch { $serveHost = "127.0.0.1" }
}
Write-Host "[reboot] starting Nostradamus API :8000 (host $serveHost)"
Start-Process -FilePath $Python -ArgumentList "scripts\serve.py","--host",$serveHost,"--port","8000" `
    -WorkingDirectory $NostraRoot -WindowStyle Hidden

$tunnelPort = 4174
$cfCfg = Join-Path $NostraRoot "config\cloudflare.json"
if (Test-Path $cfCfg) {
    try {
        $tunnelPort = [int](& $Python -c "import json;from pathlib import Path;p=Path(r'$cfCfg');d=json.loads(p.read_text(encoding='utf-8-sig'));print(int(d.get('localPort') or 4174))" 2>$null)
        if ($tunnelPort -le 0) { $tunnelPort = 4174 }
    } catch { $tunnelPort = 4174 }
}
Write-Host "[reboot] starting Nostradamus public frontend :$tunnelPort (tunnel origin)"
Start-Process -FilePath $Python -ArgumentList "scripts\serve.py","--host","127.0.0.1","--port",$tunnelPort `
    -WorkingDirectory $NostraRoot -WindowStyle Hidden

$pmpPy = Join-Path $PmpRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pmpPy)) { $pmpPy = $Python }
Write-Host "[reboot] starting PMP API :8001"
Start-Process -FilePath $pmpPy -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8001" `
    -WorkingDirectory $PmpRoot -WindowStyle Hidden

Write-Host "[reboot] starting Nostradamus autonomous supervisor..."
Start-Process powershell -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
    "-File", (Join-Path $NostraRoot "scripts\autonomous_loop.ps1")
) -WorkingDirectory $NostraRoot

if (Test-Path (Join-Path $LiveRoot "scripts\autonomous_loop.ps1")) {
    Write-Host "[reboot] starting nostradamus-live supervisor..."
    Start-Process powershell -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
        "-File", (Join-Path $LiveRoot "scripts\autonomous_loop.ps1")
    ) -WorkingDirectory $LiveRoot
}

Start-Sleep -Seconds 4
Write-Host "[reboot] health checks..."
try { Invoke-RestMethod "http://127.0.0.1:8000/api/health" -TimeoutSec 8 | Out-Null; Write-Host "  Nostradamus :8000 OK" } catch { Write-Host "  Nostradamus :8000 pending..." }
try { Invoke-RestMethod "http://127.0.0.1:$tunnelPort/api/health" -TimeoutSec 8 | Out-Null; Write-Host "  Nostradamus :$tunnelPort OK" } catch { Write-Host "  Nostradamus :$tunnelPort pending..." }
try { Invoke-RestMethod "http://127.0.0.1:8001/api/health" -TimeoutSec 8 | Out-Null; Write-Host "  PMP OK" } catch { Write-Host "  PMP pending..." }
Write-Host "[reboot] done - systems running in background"
