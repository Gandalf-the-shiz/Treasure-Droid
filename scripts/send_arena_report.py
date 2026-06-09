"""Email Trader Arena breakdown (100 genomes, top performers + simulated books).

Usage:
  python scripts/send_arena_report.py           # preview to reports/
  python scripts/send_arena_report.py --send    # SMTP via nostradamus-live config
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVE_ROOT = Path(__file__).resolve().parents[1].parent / "nostradamus-live"
if not LIVE_ROOT.exists():
    LIVE_ROOT = Path(r"c:\Users\nicho\nostradamus-live")

LEADERBOARD = REPO / "data" / "trader_arena" / "v1" / "leaderboard.json"
TRADERS = REPO / "data" / "trader_arena" / "v1" / "traders.json"
LEADERBOARD_V2 = REPO / "data" / "trader_arena" / "v2" / "leaderboard.json"
REPORTS = REPO / "reports" / "arena"


def _load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _genome_map() -> dict[int, dict]:
    doc = _load(TRADERS, {}) or {}
    return {int(t["trader_id"]): t for t in (doc.get("traders") or [])}


def _position_weights(genome: dict, result: dict, starting_cash: float = 50_000.0) -> list[dict]:
    """Mirror trader_arena.py allocation for display."""
    kelly = float(genome.get("kelly") or 0.5)
    short_frac = float(genome.get("short_frac") or 0)
    gross = starting_cash * kelly * 0.9
    n_long = max(int(result.get("nLong") or 0), 1)
    n_short = max(int(result.get("nShort") or 0), 1) if int(result.get("nShort") or 0) else 0
    long_alloc = gross * (1.0 - short_frac) / n_long if n_long else 0
    short_alloc = gross * short_frac / n_short if n_short else 0

    rows = []
    for t in result.get("trades") or []:
        side = t.get("side", "long")
        notional = long_alloc if side == "long" else short_alloc
        wt = (notional / starting_cash * 100) if starting_cash else 0
        rows.append({
            "symbol": t.get("symbol"),
            "side": side,
            "notionalUsd": round(notional, 0),
            "weightPct": round(wt, 1),
            "modelPredRetPct": round(float(t.get("ret") or 0) * 100, 2),
        })
    return rows


def _health(lb: dict, genomes: dict) -> dict:
    n = int(lb.get("nTraders") or 0)
    ok = n == 100 and len(genomes) >= 100
    return {
        "running": ok,
        "nTraders": n,
        "nGenomesOnDisk": len(genomes),
        "panelSymbols": lb.get("panelSymbols"),
        "generatedAt": lb.get("generatedAt"),
        "medianReturnPct": lb.get("medianReturnPct"),
        "pctBeatingBaseline": lb.get("pctBeatingBaseline"),
    }


def render_text(lb: dict, genomes: dict) -> str:
    h = _health(lb, genomes)
    lines = [
        "NOSTRADAMUS TRADER ARENA REPORT",
        f"Generated: {lb.get('generatedAt', 'n/a')}",
        "",
        "ARENA HEALTH",
        f"  100 agents configured: {'YES' if h['running'] else 'NO'} ({h['nTraders']} traders, {h['nGenomesOnDisk']} genomes)",
        f"  ML panel size: {h['panelSymbols']} symbols (live.csv)",
        f"  Median sim return: {h['medianReturnPct']}%",
        f"  Beat 1-trader baseline: {h['pctBeatingBaseline']}%",
        "",
        "IMPORTANT: Returns are ONE-DAY SIMULATED PnL from model pred_ret, not realized trades.",
        "",
        f"Baseline (single champion): {lb.get('baselineSingleTrader', {}).get('returnPct', 0):+.2f}%",
        "",
        "TOP 10 PERFORMERS",
    ]
    for i, t in enumerate(lb.get("top10") or [], 1):
        tid = int(t.get("traderId", -1))
        g = genomes.get(tid, {})
        lines.append("")
        lines.append(f"#{i} Trader {tid} — {t.get('family')} — sim {t.get('returnPct'):+.2f}%")
        lines.append(
            f"  Rules: min_proba={g.get('min_proba')} min_pred_ret={g.get('min_pred_ret')} "
            f"top_k={g.get('top_k')} kelly={g.get('kelly')} shorts={g.get('short_enabled')} "
            f"alt_scale={g.get('alt_scale')}"
        )
        lines.append(f"  Book ({t.get('nLong')} long, {t.get('nShort')} short) on $50k sim capital:")
        for p in _position_weights(g, t):
            lines.append(
                f"    {p['symbol']:<8} {p['side']:<6} {p['weightPct']:>5.1f}% "
                f"(${p['notionalUsd']:,.0f})  model next-day ret {p['modelPredRetPct']:+.2f}%"
            )
    lines.append("")
    lines.append("Promotion hint: " + json.dumps(lb.get("promotionHint", {}).get("traderId")))
    return "\n".join(lines)


def render_html(lb: dict, genomes: dict) -> str:
    h = _health(lb, genomes)
    status_color = "#0a0" if h["running"] else "#c00"
    rows_html = []
    for i, t in enumerate(lb.get("top10") or [], 1):
        tid = int(t.get("traderId", -1))
        g = genomes.get(tid, {})
        pos_rows = "".join(
            f"<tr><td>{p['symbol']}</td><td>{p['side']}</td>"
            f"<td>{p['weightPct']:.1f}%</td><td>${p['notionalUsd']:,.0f}</td>"
            f"<td>{p['modelPredRetPct']:+.2f}%</td></tr>"
            for p in _position_weights(g, t)
        )
        rows_html.append(f"""
        <h3>#{i} Trader {tid} — {t.get('family')} <span style="color:#06c">({t.get('returnPct'):+.2f}% sim)</span></h3>
        <p style="color:#555;font-size:13px">
          min proba {g.get('min_proba')} · min pred ret {g.get('min_pred_ret')} · top {g.get('top_k')} names ·
          Kelly {g.get('kelly')} · shorts {'on' if g.get('short_enabled') else 'off'} · unified alt-scale {g.get('alt_scale')}
        </p>
        <table border="0" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:13px">
          <tr style="background:#f0f0f0"><th>Symbol</th><th>Side</th><th>Weight</th><th>Notional</th><th>Model pred ret</th></tr>
          {pos_rows}
        </table>
        """)

    return f"""<!DOCTYPE html><html><body style="font-family:system-ui,sans-serif;max-width:720px;margin:20px">
    <h1>Trader Arena — 100 Investor Agents</h1>
    <p style="color:{status_color};font-weight:600">
      Arena status: {'Running correctly (100/100 genomes)' if h['running'] else 'CHECK — trader count mismatch'}
    </p>
    <p>Snapshot: {lb.get('generatedAt')} · Panel: {h['panelSymbols']} symbols ·
       Median sim return: {h['medianReturnPct']}% · {h['pctBeatingBaseline']}% beat baseline</p>
    <p style="background:#fff8e6;padding:10px;border-radius:6px;font-size:13px;color:#664">
      <b>Honest caveat:</b> These are research simulations on Predictor v3 <code>pred_ret</code> for one rebalance day,
      not live Robinhood fills. Warrants and penny tickers (e.g. SDAWW) can dominate; treat as strategy comparison, not profit proof.
    </p>
    <p>Baseline single trader: <b>{lb.get('baselineSingleTrader', {}).get('returnPct', 0):+.2f}%</b></p>
    <hr/>
    {''.join(rows_html)}
    <p style="color:#888;font-size:12px;margin-top:24px">Nostradamus Trader Arena · paper research only</p>
    </body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    args = ap.parse_args()

    lb = _load(LEADERBOARD)
    if not lb:
        print("ERROR: no leaderboard — run: python scripts/intelligence/trader_arena.py --respawn --pulse")
        return 1

    genomes = _genome_map()
    text = render_text(lb, genomes)
    html = render_html(lb, genomes)

    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    html_path = REPORTS / f"arena-report-{stamp}.html"
    txt_path = REPORTS / f"arena-report-{stamp}.txt"
    html_path.write_text(html, encoding="utf-8")
    txt_path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nWrote {html_path}")

    if not args.send:
        print("\n(dry run — use --send to email)")
        return 0

    sys.path.insert(0, str(LIVE_ROOT))
    try:
        from nostradamus_live.research.daily_report import send_email
    except ImportError as exc:
        print(f"ERROR: cannot import send_email from nostradamus-live: {exc}")
        return 1

    subject = (
        f"Trader Arena Top 10 — best #{lb.get('promotionHint', {}).get('traderId')} "
        f"({lb.get('promotionHint', {}).get('returnPct', 0):+.1f}% sim)"
    )
    result = send_email(subject, html, text)
    print(json.dumps(result, indent=2))
    return 0 if result.get("sent") else 1


if __name__ == "__main__":
    raise SystemExit(main())
