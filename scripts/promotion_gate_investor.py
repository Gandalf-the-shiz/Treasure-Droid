"""Champion/challenger gate for Investor v3 policy (backtest Sharpe + return)."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODEL_DIR = REPO / "models" / "v3" / "investor"
CHAMP_SUMMARY = MODEL_DIR / "summary_champion.json"
CAND_SUMMARY = REPO / "data" / "investor_v3" / "summary.json"
POLICY = MODEL_DIR / "policy.joblib"
CHAMP_POLICY = MODEL_DIR / "policy_champion.joblib"
DECISION = MODEL_DIR / "promotion-decision.json"


def _metrics(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _score(m: dict) -> float:
    ret = float(m.get("total_return_pct") or 0.0)
    sharpe = float(m.get("annualized_sharpe") or 0.0)
    dd = abs(float(m.get("max_drawdown_pct") or 0.0))
    return ret * 0.4 + sharpe * 10.0 * 0.4 - dd * 0.2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-return-delta", type=float, default=float(__import__("os").getenv("INVESTOR_PROMOTE_MIN_RET", "0.5")))
    args = ap.parse_args()

    cand = _metrics(CAND_SUMMARY)
    if not cand:
        print("DECISION=rolled_back REASON=no_candidate_summary")
        return 1

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not CHAMP_SUMMARY.exists():
        shutil.copy2(CAND_SUMMARY, CHAMP_SUMMARY)
        if POLICY.exists():
            shutil.copy2(POLICY, CHAMP_POLICY)
        DECISION.write_text(json.dumps({"decision": "promoted", "reasons": ["bootstrap_champion"]}, indent=2))
        print("DECISION=promoted")
        return 0

    champ = _metrics(CHAMP_SUMMARY)
    cs, bs = _score(cand), _score(champ)
    ret_delta = float(cand.get("total_return_pct") or 0) - float(champ.get("total_return_pct") or 0)
    reasons: list[str] = []
    if cs > bs and ret_delta >= args.min_return_delta:
        label = "promoted"
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from intelligence.forward_gate import gate_label
        label, fwd_reasons = gate_label(True)
        if label == "promoted":
            shutil.copy2(CAND_SUMMARY, CHAMP_SUMMARY)
            if POLICY.exists():
                shutil.copy2(POLICY, CHAMP_POLICY)
            reasons.append(f"composite {cs:.3f} > {bs:.3f}")
            reasons.append(f"return_delta {ret_delta:.2f}%")
            reasons.append("forward_gate_ok")
        else:
            if POLICY.exists() and CHAMP_POLICY.exists():
                shutil.copy2(CHAMP_POLICY, POLICY)
            reasons.append(f"composite {cs:.3f} > {bs:.3f} but forward_gate blocked")
            reasons.extend(fwd_reasons)
    else:
        label = "rolled_back"
        if POLICY.exists() and CHAMP_POLICY.exists():
            shutil.copy2(CHAMP_POLICY, POLICY)
        reasons.append(f"composite {cs:.3f} <= {bs:.3f} or return_delta {ret_delta:.2f}%")

    DECISION.write_text(json.dumps({"timestamp": now, "decision": label, "reasons": reasons, "candidate": cand, "champion": champ}, indent=2))
    print(f"DECISION={label}")
    return 0 if label == "promoted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
