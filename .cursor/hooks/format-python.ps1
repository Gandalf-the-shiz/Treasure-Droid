# afterFileEdit: format Python files with ruff or black when available (fail open).
$ErrorActionPreference = "SilentlyContinue"
$raw = [Console]::In.ReadToEnd()
if (-not $raw) { Write-Output "{}"; exit 0 }

try {
    $input = $raw | ConvertFrom-Json
} catch {
    Write-Output "{}"
    exit 0
}

$filePath = $input.file_path
if (-not $filePath) { $filePath = $input.path }
if (-not $filePath -or -not ($filePath -match '\.py$')) {
    Write-Output "{}"
    exit 0
}

if (-not (Test-Path -LiteralPath $filePath)) {
    Write-Output "{}"
    exit 0
}

function Invoke-Formatter($exe, $args) {
    $proc = Start-Process -FilePath $exe -ArgumentList $args -NoNewWindow -Wait -PassThru -RedirectStandardOutput "$env:TEMP\cursor-fmt-out.txt" -RedirectStandardError "$env:TEMP\cursor-fmt-err.txt"
    return $proc.ExitCode -eq 0
}

$formatted = $false
if (Get-Command ruff -ErrorAction SilentlyContinue) {
    $formatted = Invoke-Formatter "ruff" @("format", $filePath)
}
if (-not $formatted -and (Get-Command black -ErrorAction SilentlyContinue)) {
    $formatted = Invoke-Formatter "black" @($filePath)
}

Write-Output "{}"
exit 0
