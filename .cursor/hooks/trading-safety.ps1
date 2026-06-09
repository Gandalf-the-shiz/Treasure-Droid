# beforeShellExecution: ask before git push or network fetch commands (trading safety).
$ErrorActionPreference = "SilentlyContinue"
$raw = [Console]::In.ReadToEnd()
if (-not $raw) { Write-Output '{"permission":"allow"}'; exit 0 }

try {
    $input = $raw | ConvertFrom-Json
} catch {
    Write-Output '{"permission":"allow"}'
    exit 0
}

$cmd = [string]$input.command
if (-not $cmd) {
    Write-Output '{"permission":"allow"}'
    exit 0
}

if ($cmd -match '(?i)\bgit\s+push\b') {
    $json = @{
        permission    = "ask"
        user_message  = "Git push detected. Confirm this repo/branch and that no secrets or unintended trading config changes are included."
        agent_message = "Hook flagged git push — user must approve before execution."
    } | ConvertTo-Json -Compress
    Write-Output $json
    exit 0
}

if ($cmd -match '(?i)\b(curl|wget|Invoke-WebRequest|Invoke-RestMethod)\b') {
    $json = @{
        permission    = "ask"
        user_message  = "Network request command detected. Review URL and payload — avoid live trading endpoints or leaking API keys."
        agent_message = "Hook flagged a possible outbound network call."
    } | ConvertTo-Json -Compress
    Write-Output $json
    exit 0
}

Write-Output '{"permission":"allow"}'
exit 0
