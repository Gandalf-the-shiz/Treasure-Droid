"""Ultimate Model — meta-reasoning agent over Investor Arena v1/v2 results.

Reads cumulative ledgers + daily reasoning, produces improvement hypotheses.
Always scheming (paper/research); does not auto-change live gates.

Usage:
  python scripts/intelligence/ultimate_model.py
  python scripts/intelligence/ultimate_model.py --tick
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

OUT_DIR = REPO / "data" / "intelligence" / "ultimate_model"
REPORT_PATH = OUT_DIR / "latest_report.json"
JOURNAL_PATH = OUT_DIR / "journal.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _analyze_version(version: str) -> dict:
    from intelligence.arena.ledger import ranked_traders, version_summary
    from intelligence.arena.paths import ledger_path

    ranked = ranked_traders(version)
    summary = version_summary(version)
    zero_days = sum(1 for r in ranked if not (r.get("daily") or []))
    families = Counter(r.get("family") for r in ranked[:30])
    avg_trades = 0.0
    if ranked:
        avg_trades = sum((r.get("daily") or [{}])[-1].get("nTrades", 0) for r in ranked) / len(ranked)

    sym_freq = Counter()
    for r in ranked[:40]:
        for d in (r.get("daily") or [])[-1:]:
            for t in d.get("trades") or []:
                sym_freq[t.get("symbol")] += 1

    return {
        "version": version,
        "summary": summary,
        "zeroHistory": zero_days,
        "topFamilies": families.most_common(5),
        "avgTradesPerPulse": round(avg_trades, 2),
        "topSymbols": sym_freq.most_common(8),
        "top5": [
            {
                "traderId": r.get("traderId"),
                "family": r.get("family"),
                "cumulativeReturnPct": r.get("cumulativeReturnPct"),
                "selectionMode": (r.get("genome") or {}).get("selection_mode"),
            }
            for r in ranked[:5]
        ],
        "ledgerExists": ledger_path(version).exists(),
    }


def _forward_context() -> dict:
    """What Treasure Droid actually reasons over: forward fleet + live IC + alpha + readiness."""
    import os

    live_root = Path(os.getenv("NOSTRA_LIVE_ROOT", r"C:\Users\nicho\nostradamus-live"))

    def _L(p: Path) -> dict:
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    fleet = _L(REPO / "data" / "fleet" / "summary.json")
    ic = _L(REPO / "data" / "accuracy" / "v3_live_ic.json")
    alpha = _L(REPO / "data" / "accuracy" / "alpha_ic.json")
    sleeve_ic = _L(REPO / "data" / "accuracy" / "sleeve_ic.json")
    ms_loop = _L(REPO / "data" / "intelligence" / "historical" / "loop_state.json")
    readiness = _L(live_root / "data" / "gate" / "readiness.json")
    blend = alpha.get("blended_neutralized") or {}
    decayed = [
        k for k, v in (sleeve_ic.get("forward") or {}).get("by_sleeve", {}).items()
        if v.get("decayed")
    ]
    return {
        "fleetLeader": fleet.get("leader"),
        "fleetAgents": fleet.get("agents") or [],
        "liveIcDays": ic.get("n_days") or ic.get("nDays") or 0,
        "liveIcMean": ic.get("mean_ic") if ic.get("mean_ic") is not None else ic.get("meanRankIc"),
        "alphaSpread": blend.get("mean_quintile_spread"),
        "alphaIcir": blend.get("icir"),
        "sleeveWeightMode": sleeve_ic.get("weight_mode"),
        "sleeveForwardDays": (sleeve_ic.get("forward") or {}).get("n_days") or 0,
        "decayedSleeves": decayed,
        "madScientistCycle": ms_loop.get("cycle"),
        "madScientistProfile": ms_loop.get("lastProfile"),
        "madScientistChampions": (ms_loop.get("champions") or [])[:3],
        "livePermitted": bool(readiness.get("liveTradingPermitted")),
    }


def _captain_recommendations(ctx: dict) -> list[dict]:
    """Treasure Droid's forward/fleet-driven next actions (human approves from email/UI).

    Stable finding/action text so each dedupes to one registry id (no daily churn);
    live numbers go in `detail`. Medium priority => surfaced for approval, not auto-spawned
    (except the consumer-sentiment feed, which is the highest-ROI new sleeve)."""
    recs: list[dict] = []
    leader = ctx.get("fleetLeader") or {}
    laggards = [a for a in (ctx.get("fleetAgents") or []) if a.get("returnPct") is not None]
    worst = laggards[-1] if laggards else {}

    if leader:
        recs.append({
            "priority": "medium", "area": "fleet_allocation",
            "finding": "Capital should follow the forward-paper leader of the crew, not sim winners.",
            "action": "Allocate more of the Alpaca paper book to the leading forward agent and demote laggards as track records build.",
            "detail": f"Leader {leader.get('name')} {leader.get('returnPct')}% | laggard {worst.get('name')} {worst.get('returnPct')}%",
        })

    recs.append({
        "priority": "medium", "area": "data_pipelines",
        "finding": "Consumer/crowd sentiment is an ML-proxy only \u2014 a real consumer-sentiment feed is the biggest untapped uncorrelated sleeve.",
        "action": "Build a consumer-sentiment pipeline (Reddit + news + Google Trends), wire it as a new alpha sleeve and a Treasure Arena feed, and prove forward IC before weighting it.",
        "spawnSpec": {"action": "auto", "label": "Treasure Droid \u2014 consumer sentiment feed",
                      "selection_mode": "rank_v2", "feed_name": "arena_consumer_sentiment"},
    })

    decayed = ctx.get("decayedSleeves") or []
    if decayed:
        recs.append({
            "priority": "medium", "area": "sleeve_decay",
            "finding": "Per-sleeve forward IC shows decay — some alpha sleeves are hurting the blend.",
            "action": "Review decayed sleeves on the Bridge scoreboard; keep them at zero weight until trailing forward IC turns positive.",
            "detail": f"decayed: {', '.join(decayed)} | weight mode {ctx.get('sleeveWeightMode')}",
        })

    recs.append({
        "priority": "medium", "area": "arena_expansion",
        "finding": "Worth testing whether tilting genome/sleeve weights toward fundamental sleeves (PEAD, analyst revisions) raises forward IC.",
        "action": "Spawn a Treasure Arena vX with re-weighted genomes and compare its forward IC against the champion before promoting.",
        "detail": f"alpha spread {ctx.get('alphaSpread')}, ICIR {ctx.get('alphaIcir')}, sleeve forward days {ctx.get('sleeveForwardDays')}",
        "spawnSpec": {"action": "auto", "label": "Treasure Droid \u2014 re-weighted arena",
                      "selection_mode": "rank_v2", "feed_name": "arena_reweighted"},
    })

    days = ctx.get("liveIcDays") or 0
    mic = ctx.get("liveIcMean")
    supportive = bool(days >= 20 and mic is not None and mic >= 0.01)
    recs.append({
        "priority": "high", "area": "mad_scientist_lab",
        "finding": "Mad Scientist Lab walks 500 genomes day-by-day on the 2yr historical panel (matching live outputs). Survivors need forward paper proof next.",
        "action": "Review lab leaderboard on Bridge; ensure weekly lab run promotes shadow fleet agents; kill laggards after 20d forward.",
        "detail": f"sleeve forward days {ctx.get('sleeveForwardDays')}, weight mode {ctx.get('sleeveWeightMode')}",
    })

    recs.append({
        "priority": "medium", "area": "model_promotion",
        "finding": "ML challengers should only be promoted on forward proof, never backtest.",
        "action": ("Forward IC clears the gate \u2014 run promotion_gate_v3 + promotion_gate_investor to promote challengers."
                   if supportive else
                   "Keep accumulating forward IC before promoting challengers; gate not yet cleared."),
        "detail": f"live forward IC {mic} over {days}/20 days",
    })
    return recs


def _build_recommendations(v1: dict, v2: dict, compare: dict) -> list[dict]:
    recs = []
    v2_wins = compare.get("v2BeatingV1")
    if v2_wins is True:
        recs.append({
            "priority": "high",
            "area": "arena_selection",
            "finding": "Arena v2 (rank-unified) leads v1 on mean cumulative return.",
            "action": "Consider promoting rank_v2 selection into investor manifests after forward validation.",
        })
    elif v2_wins is False:
        recs.append({
            "priority": "medium",
            "area": "arena_selection",
            "finding": "Arena v1 still ahead on cumulative mean — threshold gate may be filtering noise.",
            "action": "Keep v1 for production hints; use v2 for diversification research only.",
        })

    if v1.get("avgTradesPerPulse", 0) < 1.5:
        recs.append({
            "priority": "high",
            "area": "v1_starvation",
            "finding": "v1 agents often take 0-1 trades (strict proba/pred_ret filters on sparse panel).",
            "action": "Already addressed in v2; do not tighten v1 further.",
        })

    if v2.get("avgTradesPerPulse", 0) > 3:
        recs.append({
            "priority": "info",
            "area": "v2_diversification",
            "finding": "v2 holds more names per book — better use of 800-symbol panel.",
            "action": "Monitor forward IC; sim returns still upper bound.",
        })

    top_syms = set(s for s, _ in (v1.get("topSymbols") or [])[:3])
    if top_syms and len(top_syms) <= 3:
        recs.append({
            "priority": "high",
            "area": "concentration_risk",
            "finding": f"Winners cluster in {list(top_syms)} (often warrants).",
            "action": "Megamind will update the best v3+ arm or spawn a new one (profit-focused) — v1/v2 frozen.",
            "spawnSpec": {
                "action": "auto",
                "label": "Megamind experimental — liquidity-aware rank panel",
                "selection_mode": "rank_v2",
                "feed_name": "arena_v3_liquidity_panel",
            },
        })

    from intelligence.arena.operating import champion_version

    if not champion_version() and v2_wins is True:
        recs.append({
            "priority": "medium",
            "area": "arena_expansion",
            "finding": "v2 leads v1; no experimental arm beyond frozen baselines yet.",
            "action": "Megamind will spawn or improve v3+ to hunt profit beyond frozen baselines.",
            "spawnSpec": {
                "action": "auto",
                "label": "Megamind rank-unified experimental",
                "selection_mode": "rank_v2",
                "feed_name": "arena_v3_panel",
            },
        })

    recs.append({
        "priority": "high",
        "area": "data_pipelines",
        "finding": "Insider Form 4 and Reddit crowd feeds remain weak or blocked.",
        "action": "Keep SEC insider fetch on schedule; crowd uses ML-proxy until Reddit API restored.",
    })

    recs.append({
        "priority": "critical",
        "area": "live_gate",
        "finding": "Arena sim profit does not prove forward edge.",
        "action": "Ultimate Model must not open live trading — only suggest paper experiments.",
    })

    # Treasure Droid captain — forward/fleet-driven next actions
    try:
        recs.extend(_captain_recommendations(_forward_context()))
    except Exception as exc:  # noqa: BLE001
        print(f"[treasure-droid] captain recs skipped: {exc}", flush=True)

    from intelligence.arena.decision import enrich_spawn_spec

    report_stub = {"compare": compare, "v1": v1, "v2": v2}
    for r in recs:
        if r.get("spawnSpec") is not None or (r.get("area") or "") in (
            "concentration_risk", "arena_expansion", "arena_spawn", "data_pipelines"
        ):
            if "spawnSpec" not in r:
                r["spawnSpec"] = {"action": "auto"}
            r["spawnSpec"] = enrich_spawn_spec(r, report_stub)
            if r["spawnSpec"].get("reason"):
                r["megamindPlan"] = (
                    f"{r['spawnSpec'].get('action', 'auto').upper()} "
                    f"{r['spawnSpec'].get('version') or 'new arm'}: {r['spawnSpec']['reason']}"
                )
    return recs


def _llm_narrative(payload: dict) -> str | None:
    try:
        from npu_llm import generate_text
        prompt = (
            "You are Treasure Droid, a rusted robot-pirate captain commanding a fleet of ML "
            "trading agents hunting market gold. Given the arena + forward fleet stats, write 3 short "
            "paragraphs: what's working, what's failing, and the single most valuable next build "
            "(e.g. a new data pipeline, a re-weighted Treasure Arena arm, or promoting a model). "
            "Be skeptical of simulated returns \u2014 only forward paper is real treasure.\n\n"
            f"DATA:\n{json.dumps(payload, indent=2)[:6000]}"
        )
        return generate_text(prompt, max_tokens=600)
    except Exception:
        return None


def run_tick() -> dict:
    from intelligence.arena.ledger import compare_series
    from intelligence.arena.operating import ensure_operating_model, operating_status

    ensure_operating_model()
    op = operating_status()
    v1 = _analyze_version("v1")
    v2 = _analyze_version("v2")
    compare = compare_series()
    recommendations = _build_recommendations(v1, v2, compare)

    narrative = (
        f"Treasure Droid tick {_now()} — captain of the fleet, hunting market gold (sim arena scoreboard; "
        f"forward paper is the only real treasure). "
        f"v1 {v1['summary'].get('meanCumulativePct')}% vs v2 {v2['summary'].get('meanCumulativePct')}% "
        f"(v2 beating v1: {compare.get('v2BeatingV1')}). "
        f"Operating: pulse {op.get('pulseVersions')}; champion {op.get('champion')}; "
        f"challenger {op.get('challenger')}; archived {op.get('archived')}. "
        "v1/v2 frozen; Megamind evolves champion + optional challenger; harvest uses all pools."
    )
    llm = _llm_narrative({"v1": v1, "v2": v2, "compare": compare, "recommendations": recommendations})
    if llm:
        narrative += "\n\nLLM synthesis:\n" + llm

    doc = {
        "generatedAt": _now(),
        "status": "scheming",
        "v1": v1,
        "v2": v2,
        "compare": compare,
        "recommendations": recommendations,
        "narrative": narrative,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    with JOURNAL_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": _now(), "narrative": narrative[:2000]}) + "\n")
    print(f"[ultimate-model] report written {REPORT_PATH}", flush=True)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tick", action="store_true")
    args = ap.parse_args()
    run_tick()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
