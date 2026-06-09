# beforeSubmitPrompt: block obvious secret patterns in user prompts (fail open on errors).
$ErrorActionPreference = "SilentlyContinue"
$raw = [Console]::In.ReadToEnd()
if (-not $raw) { Write-Output '{"continue":true}'; exit 0 }

try {
    $input = $raw | ConvertFrom-Json
} catch {
    Write-Output '{"continue":true}'
    exit 0
}

$prompt = [string]$input.prompt
if (-not $prompt) { $prompt = [string]$input.text }
if (-not $prompt) {
    Write-Output '{"continue":true}'
    exit 0
}

$patterns = @(
    'BEGIN\s+(RSA\s+)?PRIVATE\s+KEY',
    'API_KEY\s*=\s*["\']?sk-',
    'OPENAI_API_KEY\s*=\s*["\']?sk-',
    'cursorApiKey["\']?\s*:\s*["\'][^"\']{20,}',
    'megamind\.secrets\.json',
    '\.env\b.*(password|secret|token)\s*='
)

foreach ($pat in $patterns) {
    if ($prompt -match $pat) {
        $json = @{
            continue      = $false
            user_message  = "Prompt may contain secrets (API key, private key, or .env material). Remove secrets before submitting."
            agent_message = "Hook blocked prompt due to likely secret pattern."
        } | ConvertTo-Json -Compress
        Write-Output $json
        exit 0
    }
}

Write-Output '{"continue":true}'
exit 0
