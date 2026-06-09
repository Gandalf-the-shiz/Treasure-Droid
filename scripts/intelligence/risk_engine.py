"""Pre-trade risk filters — enforced on every manifest before export."""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO / "config" / "trading_policy.json"


def _load_policy() -> dict:
    if POLICY_PATH.exists():
        try:
            return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "max_gross_exposure": 0.90,
        "max_position_frac": 0.20,
        "min_proba": 0.60,
        "min_pred_ret": 0.020,
        "max_orders": 12,
    }


def enforce_manifest(manifest: dict) -> dict:
    """Drop or shrink orders that violate risk policy."""
    policy = _load_policy()
    risk = manifest.setdefault("risk", {})
    orders = list(manifest.get("orders") or [])
    if not orders:
        manifest["riskEngine"] = {"enforced": True, "dropped": 0}
        return manifest

    max_orders = int(policy.get("max_orders") or os.getenv("BROKER_MAX_ORDERS", "12"))
    min_proba = float(policy.get("min_proba") or risk.get("minProba") or 0.60)
    min_pred = float(policy.get("min_pred_ret") or 0.020)
    max_pos_frac = float(policy.get("max_position_frac") or risk.get("maxPositionFrac") or 0.20)
    portfolio = float((manifest.get("portfolio") or {}).get("valueUsd") or 100_000)

    kept = []
    dropped = []
    for o in orders:
        meta = o.get("metadata") or {}
        proba = float(meta.get("proba_up") or 0)
        pred_ret = float(meta.get("pred_ret") or 0)
        notional = float(o.get("notional_usd") or 0)
        if proba < min_proba:
            dropped.append({"order_id": o.get("order_id"), "reason": f"proba {proba} < {min_proba}"})
            continue
        if pred_ret < min_pred:
            dropped.append({"order_id": o.get("order_id"), "reason": f"pred_ret {pred_ret} < {min_pred}"})
            continue
        cap = portfolio * max_pos_frac
        if notional > cap:
            o["notional_usd"] = round(cap, 2)
        kept.append(o)

    kept = kept[:max_orders]
    manifest["orders"] = kept
    manifest["riskEngine"] = {
        "enforced": True,
        "dropped": len(dropped),
        "dropReasons": dropped[:20],
        "minProba": min_proba,
        "minPredRet": min_pred,
        "maxOrders": max_orders,
    }
    notes = risk.setdefault("notes", [])
    notes.append(f"risk_engine: kept {len(kept)} orders, dropped {len(dropped)}")
    return manifest
