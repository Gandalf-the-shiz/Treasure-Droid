---
name: nostradamus-commit
description: >-
  Git commit workflow for Nostradamus: status, diff, log, draft message, no
  secrets, ask before commit. Use when the user asks to commit changes or prepare
  a git commit in this repository.
disable-model-invocation: true
---

# Nostradamus commit protocol

## Purpose

Create commits only when the user explicitly requests it. Never commit proactively.

## Checklist (run in parallel first)

```powershell
git status
git diff
git diff --staged
git log -5 --oneline
```

## Before committing

1. **Never commit** `.env`, `config/megamind.secrets.json`, `config/cloudflare.json`, API keys, or `.cache/` dumps.
2. Warn if staged files look like secrets.
3. Draft a 1–2 sentence message focused on **why**, matching recent `git log` style.
4. If unclear whether to commit, **ask first**.

## Commit sequence

```powershell
git add <relevant-files>
git commit -m "$( @'
Your message here.

'@ )"
git status
```

Use HEREDOC-style PowerShell here-strings for multi-line messages.

## Do NOT

- `git config` changes
- `--no-verify`, `--amend` (unless user explicitly requests and conditions met)
- `push --force` to main/master
- Commit unless user said "commit" or equivalent
- Push unless user explicitly asks

## Amend rules (all must be true)

1. User explicitly requested amend, OR pre-commit hook auto-modified files
2. HEAD commit was created in this conversation
3. Commit has **not** been pushed

If commit **failed** due to hook, fix and create a **new** commit — never amend.
