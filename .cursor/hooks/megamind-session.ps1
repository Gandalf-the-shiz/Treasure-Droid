# SessionStart: inject pending Megamind Cursor prompt into new Agent sessions.
$ErrorActionPreference = "SilentlyContinue"
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $repo) { $repo = Get-Location }
$pending = Join-Path $repo "data\intelligence\megamind\pending_for_agent.json"
$promptFile = Join-Path $repo "data\intelligence\megamind\CURRENT_AGENT_PROMPT.md"
if (-not (Test-Path $pending)) {
    Write-Output "{}"
    exit 0
}
# Slim injection: full brief lives in megamind-active-task.mdc (alwaysApply). Avoid duplicating 6k+ chars here.
$taskId = ""
try {
    $pendingDoc = Get-Content $pending -Raw -Encoding UTF8 | ConvertFrom-Json
    $taskId = $pendingDoc.recommendationId
} catch { }
$ctx = @"
MEGAMIND APPROVED TASK queued$(if ($taskId) { " ($taskId)" }).
Brief: .cursor/rules/megamind-active-task.mdc and data/intelligence/megamind/CURRENT_AGENT_PROMPT.md.
Use skill concentration-risk for implementation steps. Arena policy is in megamind-arena-policy.mdc.
"@
$obj = @{ additional_context = $ctx }
Write-Output ($obj | ConvertTo-Json -Compress -Depth 4)
