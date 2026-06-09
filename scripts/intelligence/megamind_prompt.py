"""Build production-grade Cursor Agent prompts for Megamind recommendations."""
from __future__ import annotations

import json
from pathlib import Path

from intelligence.arena.policy import ARENA_POLICY_MARKDOWN

REPO = Path(__file__).resolve().parents[2]
LIVE = Path(r"c:\Users\nicho\nostradamus-live")


def _fallback_prompt(rec: dict, report: dict) -> str:
    v1 = (report.get("v1") or {}).get("summary") or {}
    v2 = (report.get("v2") or {}).get("summary") or {}
    cmp = report.get("compare") or {}
    plan = rec.get("megamindPlan") or (rec.get("spawnSpec") or {}).get("reason") or ""
    return f"""# Megamind: {rec.get('area', 'improvement')} ({rec.get('priority', 'medium')})

## North star
Prepare the best **Robinhood AI agent** candidate: simulated trades on **real market data** (live ML panel + feeds), PnL from model `pred_ret` vs real symbols — not live fills until readiness permits.

## Objective
{rec.get('action', 'Implement the approved Megamind recommendation.')}
{f'{chr(10)}**Megamind arena plan:** {plan}' if plan else ''}

## Context
- **Finding:** {rec.get('finding', '')}
- **Arena v1** mean cumulative: {v1.get('meanCumulativePct')}% · best trader #{v1.get('topTraderId')}
- **Arena v2** mean cumulative: {v2.get('meanCumulativePct')}% · best trader #{v2.get('topTraderId')}
- **v2 beating v1:** {cmp.get('v2BeatingV1')}
- Arena P&L is **simulated** from `pred_ret` on `data/predictions_v3/live.csv` — not live fills.

## Repos
- Primary: `Nostradamus_remote_audit` (intelligence, arena, dashboard, `scripts/serve.py`)
- Email/UI bridge: `nostradamus-live` (`nostradamus_live/research/daily_report.py`, `nostra_ui_bridge.py`)

## Implementation steps
1. Read existing code paths for `{rec.get('area')}` — search before editing.
2. Implement the smallest correct change that satisfies the finding; match local naming and patterns.
3. Wire into post-close flow if needed (`scripts/daily_market_close.ps1`, `megamind.py --tick`).
4. Verify: run relevant script or hit API; do not weaken `readiness` / live trading gates.

## Acceptance criteria
- [ ] Change addresses the finding with a measurable outcome (test, API field, or logged artifact).
- [ ] No secrets committed; paper/dryRun defaults preserved.
- [ ] Dashboard or daily email still loads if UI touched.

## Do NOT
- Open live trading or bypass the readiness gate to improve backtest metrics.
- **Delete, respawn, or modify Investor Arena v1 or v2** — only spawn new versions (v3+) or new data feeds.
- Respawn arena genomes unless explicitly requested (`regenerate_all.ps1 -RespawnArena` only).

{ARENA_POLICY_MARKDOWN}

## When done
Update `data/intelligence/megamind/registry.json` recommendation `{rec.get('id')}` status to `implemented` if appropriate.
"""


def build_cursor_prompt(rec: dict, report: dict) -> str:
    """LLM-crafted Cursor prompt when NPU/LLM available; else structured fallback."""
    payload = {
        "recommendation": rec,
        "arena_v1": (report.get("v1") or {}).get("summary"),
        "arena_v2": (report.get("v2") or {}).get("summary"),
        "compare": {
            "v2BeatingV1": (report.get("compare") or {}).get("v2BeatingV1"),
        },
        "top_symbols_v1": (report.get("v1") or {}).get("topSymbols"),
        "repos": [str(REPO), str(LIVE) if LIVE.exists() else "nostradamus-live"],
    }
    try:
        from npu_llm import generate_text
        system = (
            "You write implementation prompts for Cursor Composer/Agent. "
            "Output ONLY markdown the agent can execute — no preamble. "
            "Be specific: file paths, function names to search, acceptance tests, safety rails. "
            "This is a quant research stack (Nostradamus); never suggest disabling paper/live gates."
        )
        user = (
            f"Write an excellent Cursor Agent prompt from this Megamind approval:\n\n"
            f"{json.dumps(payload, indent=2)[:7000]}\n\n"
            "Required sections: # Title, ## Objective, ## Context, ## Files to inspect, "
            "## Implementation steps (numbered), ## Acceptance criteria (checkboxes), ## Do NOT."
        )
        text = generate_text(f"{system}\n\n{user}", max_tokens=1200)
        if text and len(text.strip()) > 200:
            header = (
                f"<!-- Megamind {rec.get('id')} · {rec.get('area')} · approved task -->\n\n"
            )
            return header + text.strip()
    except Exception:
        pass
    return _fallback_prompt(rec, report)
