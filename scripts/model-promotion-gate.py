"""
model-promotion-gate.py

Centralized promotion gate for champion/challenger model handling.

Implements a statistically aware, multi-metric decision policy so model promotion
is not based on a single raw accuracy number.

Decision inputs:
  - Candidate metadata: models/v2/metadata.json
  - Baseline metadata:  models/v2/metadata_prev.json (if present)
  - Candidate test sample size from trainingStats.testSamples

Decision outputs:
  - models/v2/promotion-decision.json
  - updated metadata_prev.json when promoted
  - rollback from backup directory when not promoted
  - appended retrain-history entry
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class MetricPack:
    accuracy: float | None
    auc: float | None
    f1: float | None
    reg_mae: float | None
    test_samples: int


def _safe_float(v, default=None):
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _wilson_lower_bound(acc: float | None, n: int, z: float = 1.96) -> float | None:
    if acc is None or n <= 0:
        return None
    p = max(0.0, min(1.0, float(acc)))
    denom = 1.0 + (z * z) / n
    center = p + (z * z) / (2 * n)
    spread = z * math.sqrt((p * (1 - p) + (z * z) / (4 * n)) / n)
    return (center - spread) / denom


def _extract_metrics(meta: dict) -> MetricPack:
    tm = meta.get("testMetrics") or {}
    ts = meta.get("trainingStats") or {}
    return MetricPack(
        accuracy=_safe_float(tm.get("accuracy")),
        auc=_safe_float(tm.get("auc")),
        f1=_safe_float(tm.get("f1")),
        reg_mae=_safe_float(tm.get("reg_mae")),
        test_samples=int(ts.get("testSamples") or 0),
    )


def _composite_score(m: MetricPack) -> float:
    # Weighted composite emphasizing direction quality + ranking quality.
    acc = m.accuracy if m.accuracy is not None else 0.0
    auc = m.auc if m.auc is not None else 0.0
    f1 = m.f1 if m.f1 is not None else 0.0
    return 0.50 * acc + 0.30 * auc + 0.20 * f1


def _decide(candidate: MetricPack, baseline: MetricPack) -> tuple[str, list[str], dict]:
    reasons: list[str] = []
    diagnostics: dict = {}

    cand_lb = _wilson_lower_bound(candidate.accuracy, candidate.test_samples)
    base_lb = _wilson_lower_bound(baseline.accuracy, baseline.test_samples)
    diagnostics["wilson"] = {
        "candidateLower95": round(cand_lb, 6) if cand_lb is not None else None,
        "baselineLower95": round(base_lb, 6) if base_lb is not None else None,
    }

    cand_comp = _composite_score(candidate)
    base_comp = _composite_score(baseline)
    diagnostics["composite"] = {
        "candidate": round(cand_comp, 6),
        "baseline": round(base_comp, 6),
        "delta": round(cand_comp - base_comp, 6),
    }

    # Hard no-regression constraints.
    if candidate.accuracy is not None and baseline.accuracy is not None:
        if candidate.accuracy < baseline.accuracy - 0.002:
            reasons.append("accuracy_regressed")
    if candidate.auc is not None and baseline.auc is not None:
        if candidate.auc < baseline.auc - 0.002:
            reasons.append("auc_regressed")
    if candidate.reg_mae is not None and baseline.reg_mae is not None and baseline.reg_mae > 0:
        if candidate.reg_mae > baseline.reg_mae * 1.03:
            reasons.append("regression_mae_regressed")

    if reasons:
        return "rolled_back", reasons, diagnostics

    # Promotion conditions:
    # 1) Better confidence-adjusted accuracy bound, OR
    # 2) composite quality improves by at least 0.001.
    if cand_lb is not None and base_lb is not None and cand_lb > base_lb:
        reasons.append("wilson_lower_bound_improved")
        return "promoted", reasons, diagnostics

    if cand_comp >= base_comp + 0.001:
        reasons.append("composite_score_improved")
        return "promoted", reasons, diagnostics

    reasons.append("no_statistically_meaningful_improvement")
    return "rolled_back", reasons, diagnostics


def _restore_backup(models_dir: Path, backup_dir: Path) -> None:
    if not backup_dir.exists():
        return
    if models_dir.exists():
        for item in models_dir.iterdir():
            if item.name == "metadata_prev.json":
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
    else:
        models_dir.mkdir(parents=True, exist_ok=True)

    for item in backup_dir.iterdir():
        target = models_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
    shutil.rmtree(backup_dir, ignore_errors=True)


def _append_history(history_path: Path, entry: dict) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    if history_path.exists():
        with history_path.open() as f:
            data = json.load(f)
    else:
        data = {"entries": []}
    data.setdefault("entries", []).append(entry)
    with history_path.open("w") as f:
        json.dump(data, f, indent=2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", default="models/v2")
    ap.add_argument("--baseline-metadata", default="models/v2/metadata_prev.json")
    ap.add_argument("--backup-dir", default="models/v2_backup")
    ap.add_argument("--history-path", default="data/accuracy/retrain-history.json")
    ap.add_argument("--decision-path", default="models/v2/promotion-decision.json")
    args = ap.parse_args()

    models_dir = Path(args.models_dir)
    candidate_meta_path = models_dir / "metadata.json"
    baseline_meta_path = Path(args.baseline_metadata)
    backup_dir = Path(args.backup_dir)
    history_path = Path(args.history_path)
    decision_path = Path(args.decision_path)

    if not candidate_meta_path.exists():
        print("DECISION=rolled_back")
        print("REASON=no_candidate_metadata")
        return

    with candidate_meta_path.open() as f:
        candidate_meta = json.load(f)
    candidate = _extract_metrics(candidate_meta)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not baseline_meta_path.exists():
        baseline_meta_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate_meta_path, baseline_meta_path)
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)

        decision = {
            "timestamp": now,
            "decision": "promoted",
            "reasons": ["no_baseline_available"],
            "candidate": candidate_meta.get("testMetrics") or {},
            "baseline": None,
            "diagnostics": {},
        }
        decision_path.parent.mkdir(parents=True, exist_ok=True)
        with decision_path.open("w") as f:
            json.dump(decision, f, indent=2)

        _append_history(history_path, {
            "timestamp": now,
            "decision": "promoted",
            "reasons": ["no_baseline_available"],
            "previousAccuracy": None,
            "newAccuracy": candidate.accuracy,
            "sampleSize": candidate.test_samples,
        })

        print("DECISION=promoted")
        print("REASON=no_baseline_available")
        return

    with baseline_meta_path.open() as f:
        baseline_meta = json.load(f)
    baseline = _extract_metrics(baseline_meta)

    decision_label, reasons, diagnostics = _decide(candidate, baseline)

    if decision_label == "promoted":
        shutil.copy2(candidate_meta_path, baseline_meta_path)
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
    else:
        _restore_backup(models_dir, backup_dir)

    decision_doc = {
        "timestamp": now,
        "decision": decision_label,
        "reasons": reasons,
        "candidate": candidate_meta.get("testMetrics") or {},
        "baseline": baseline_meta.get("testMetrics") or {},
        "diagnostics": diagnostics,
    }
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    with decision_path.open("w") as f:
        json.dump(decision_doc, f, indent=2)

    _append_history(history_path, {
        "timestamp": now,
        "decision": decision_label,
        "reasons": reasons,
        "previousAccuracy": baseline.accuracy,
        "newAccuracy": candidate.accuracy,
        "sampleSize": candidate.test_samples,
        "diagnostics": diagnostics,
    })

    print(f"DECISION={decision_label}")
    print(f"REASON={','.join(reasons)}")


if __name__ == "__main__":
    main()
