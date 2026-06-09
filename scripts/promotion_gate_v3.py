"""Champion/challenger promotion gate for Predictor v3."""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "model_promotion_gate",
    Path(__file__).resolve().parent / "model-promotion-gate.py",
)
_mpg = importlib.util.module_from_spec(_spec)
assert _spec.loader
_spec.loader.exec_module(_mpg)

MetricPack = _mpg.MetricPack
_decide = _mpg._decide
_append_history = _mpg._append_history


def _v3_metrics(meta: dict) -> MetricPack:
    test = (meta.get("metrics") or {}).get("test") or {}
    return MetricPack(
        accuracy=float(test["accuracy"]) if test.get("accuracy") is not None else None,
        auc=float(test["auc"]) if test.get("auc") is not None else None,
        f1=float(test["f1"]) if test.get("f1") is not None else None,
        reg_mae=float(test["reg_mae"]) if test.get("reg_mae") is not None else None,
        test_samples=int(test.get("n") or 0),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", default="models/v3/predictor")
    ap.add_argument("--champion-meta", default="models/v3/predictor/metadata_champion.json")
    ap.add_argument("--backup-dir", default="models/v3/predictor_challenger_backup")
    ap.add_argument("--decision-path", default="models/v3/predictor/promotion-decision.json")
    ap.add_argument("--history-path", default="data/learning/promotion-history.json")
    args = ap.parse_args()

    models_dir = Path(args.models_dir)
    cand_path = models_dir / "metadata.json"
    champ_path = Path(args.champion_meta)
    backup_dir = Path(args.backup_dir)
    decision_path = Path(args.decision_path)

    if not cand_path.exists():
        print("DECISION=rolled_back")
        print("REASON=no_candidate_metadata")
        return 1

    candidate_meta = json.loads(cand_path.read_text(encoding="utf-8"))
    candidate = _v3_metrics(candidate_meta)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not champ_path.exists():
        shutil.copy2(cand_path, champ_path)
        decision_path.write_text(
            json.dumps({"timestamp": now, "decision": "promoted", "reasons": ["no_champion_available"]}, indent=2),
            encoding="utf-8",
        )
        print("DECISION=promoted")
        return 0

    champion_meta = json.loads(champ_path.read_text(encoding="utf-8"))
    baseline = _v3_metrics(champion_meta)
    label, reasons, diagnostics = _decide(candidate, baseline)

    if label == "promoted":
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from intelligence.forward_gate import gate_label
        label, fwd_reasons = gate_label(True)
        if label != "promoted":
            reasons = list(reasons) + fwd_reasons
            diagnostics = dict(diagnostics or {})
            diagnostics["forward_gate"] = fwd_reasons

    if label != "promoted" and backup_dir.exists():
        shutil.copy2(champ_path, models_dir / "metadata.json")
        shutil.rmtree(backup_dir, ignore_errors=True)
    elif label == "promoted":
        shutil.copy2(cand_path, champ_path)
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)

    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(
        json.dumps(
            {
                "timestamp": now,
                "decision": label,
                "reasons": reasons,
                "diagnostics": diagnostics,
                "candidate": candidate_meta.get("metrics", {}).get("test"),
                "champion": champion_meta.get("metrics", {}).get("test"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _append_history(Path(args.history_path), {"timestamp": now, "decision": label, "reasons": reasons})
    print(f"DECISION={label}")
    print(f"REASON={','.join(reasons)}")
    return 0 if label == "promoted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
