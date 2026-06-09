"""Benchmark NPU (QNN/HTP) vs CPU on ML workloads we actually use.

Workloads:
  1. Penny Wolf champion ONNX — sub-$5 heat scoring (many symbols per scan)
  2. FinBERT sentiment — headline enrichment for investor decisions

Usage:
  python scripts/benchmark_npu.py
  python scripts/benchmark_npu.py --quick
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PENNY_ONNX = REPO / "models" / "penny" / "champion.onnx"
SENTIMENT_ONNX = REPO / "models" / "sentiment" / "model.onnx"
OUT_PATH = REPO / "data" / "learning" / "npu_benchmark.json"

sys.path.insert(0, str(REPO / "scripts"))

HEADLINES = [
    "Fed holds rates steady, signals patience on cuts",
    "Tech stocks rally as AI spending accelerates",
    "Oil slips on demand concerns in China",
    "Meme stock surges 40% on retail buying frenzy",
    "Bank earnings beat estimates, shares jump",
    "Biotech firm wins FDA approval, stock doubles",
    "Dollar strengthens as yields climb",
    "Retail sales disappoint, recession fears grow",
]


def _percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def _bench_times(run_fn, warmup: int, runs: int) -> dict:
    for _ in range(warmup):
        run_fn()
    samples: list[float] = []
    t0 = time.perf_counter()
    for _ in range(runs):
        s = time.perf_counter()
        run_fn()
        samples.append((time.perf_counter() - s) * 1000.0)
    total_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "runs": runs,
        "total_ms": round(total_ms, 2),
        "mean_ms": round(statistics.mean(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(_percentile(samples, 95), 3),
        "min_ms": round(min(samples), 3),
        "max_ms": round(max(samples), 3),
        "per_sec": round(runs / (total_ms / 1000.0), 2) if total_ms > 0 else 0,
    }


def _session_cpu_only(model_path: Path):
    import onnxruntime as ort
    return ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])


def _session_npu(model_path: Path):
    from npu_runtime import create_inference_session
    return create_inference_session(model_path)


def benchmark_penny(*, warmup: int, runs: int, batch: int) -> dict | None:
    if not PENNY_ONNX.exists():
        return None
    import numpy as np

    meta_path = PENNY_ONNX.with_suffix(".onnx.meta.json")
    n_feat = 13
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        n_feat = len(meta.get("feature_order") or []) or n_feat

    def run_provider(label: str, factory):
        sess = factory(PENNY_ONNX)
        providers = sess.get_providers()
        inp = sess.get_inputs()[0].name
        X = np.random.randn(batch, n_feat).astype(np.float32)

        def one():
            sess.run(None, {inp: X})

        stats = _bench_times(one, warmup, runs)
        del sess
        return {"provider_label": label, "session_providers": providers, "batch": batch, **stats}

    return {
        "model": str(PENNY_ONNX),
        "features": n_feat,
        "npu": run_provider("QNN (HTP)", _session_npu),
        "cpu": run_provider("CPU", _session_cpu_only),
    }


def benchmark_sentiment(*, warmup: int, runs: int, batch: int) -> dict | None:
    if not SENTIMENT_ONNX.exists():
        return None

    import numpy as np
    from sentiment_encoder import SentimentEncoder, WordPieceTokenizer, VOCAB_PATH

    enc = SentimentEncoder()
    tok = WordPieceTokenizer(VOCAB_PATH, max_len=96)
    headlines = (HEADLINES * ((batch // len(HEADLINES)) + 1))[:batch]
    input_ids, attn = tok.encode_batch(headlines)
    ids_arr = np.asarray(input_ids, dtype=np.int64)
    mask_arr = np.asarray(attn, dtype=np.int64)
    tok_type = np.zeros_like(ids_arr)

    def run_provider(label: str, factory):
        sess = factory(SENTIMENT_ONNX)
        providers = sess.get_providers()
        wanted = {i.name for i in sess.get_inputs()}
        feeds = {}
        if "input_ids" in wanted:
            feeds["input_ids"] = ids_arr
        if "attention_mask" in wanted:
            feeds["attention_mask"] = mask_arr
        if "token_type_ids" in wanted:
            feeds["token_type_ids"] = tok_type

        def one():
            sess.run(None, feeds)

        stats = _bench_times(one, warmup, runs)
        del sess
        return {"provider_label": label, "session_providers": providers, "batch": batch, **stats}

    return {
        "model": str(SENTIMENT_ONNX),
        "model_mb": round(SENTIMENT_ONNX.stat().st_size / 1e6, 1),
        "npu": run_provider("QNN (HTP)", _session_npu),
        "cpu": run_provider("CPU", _session_cpu_only),
    }


def benchmark_penny_live_path(*, runs: int) -> dict | None:
    """End-to-end penny_ml.score_candles (NPU path when champion exists)."""
    try:
        from penny_ml.score_live import score_candles, champion_meta
    except ImportError:
        return None
    if not champion_meta():
        return None

    import json as _json
    hist = REPO / "data" / "historical"
    candles = None
    sym = None
    for fp in sorted(hist.glob("*.json"))[:5]:
        if fp.name.startswith("manifest"):
            continue
        try:
            data = _json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError):
            continue
        for s, payload in (data.get("stocks") or {}).items():
            c = (payload or {}).get("candles") or []
            if len(c) >= 80:
                candles, sym = c, s
                break
        if candles:
            break
    if not candles:
        return None

    def one():
        score_candles(candles)

    stats = _bench_times(one, warmup=2, runs=runs)
    return {"symbol": sym, "path": "penny_ml.score_live", **stats}


def _speedup(npu: dict, cpu: dict) -> float | None:
    if not npu or not cpu or not cpu.get("mean_ms"):
        return None
    return round(cpu["mean_ms"] / npu["mean_ms"], 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="Fewer iterations")
    args = ap.parse_args()

    if args.quick:
        warmup, runs, penny_batch, sent_batch = 1, 5, 16, 4
    else:
        warmup, runs, penny_batch, sent_batch = 3, 20, 32, 8

    from npu_runtime import write_status, primary_provider, qnn_devices
    write_status({"benchmark": True})

    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "soc": "Snapdragon X",
        "primary": primary_provider(),
        "qnnDevices": len(qnn_devices()),
        "workloads": {},
    }

    print(f"[bench] primary={report['primary']} qnn_devices={report['qnnDevices']}", flush=True)

    penny = benchmark_penny(warmup=warmup, runs=runs, batch=penny_batch)
    if penny:
        penny["speedup_mean"] = _speedup(penny["npu"], penny["cpu"])
        report["workloads"]["penny_champion"] = penny
        print(f"[bench] Penny Wolf batch={penny_batch}: "
              f"NPU {penny['npu']['mean_ms']}ms vs CPU {penny['cpu']['mean_ms']}ms "
              f"(speedup {penny['speedup_mean']}x)", flush=True)

    sent = benchmark_sentiment(warmup=max(1, warmup), runs=min(runs, 10), batch=sent_batch)
    if sent:
        sent["speedup_mean"] = _speedup(sent["npu"], sent["cpu"])
        report["workloads"]["finbert_sentiment"] = sent
        print(f"[bench] FinBERT batch={sent_batch}: "
              f"NPU {sent['npu']['mean_ms']}ms vs CPU {sent['cpu']['mean_ms']}ms "
              f"(speedup {sent['speedup_mean']}x)", flush=True)

    live = benchmark_penny_live_path(runs=10 if not args.quick else 5)
    if live:
        report["workloads"]["penny_live_score"] = live
        print(f"[bench] penny live score: {live['mean_ms']}ms mean", flush=True)

    report["notes"] = [
        "Penny champion: simulates one scan batch of heat/ML scores.",
        "FinBERT: batch headline scoring for enrich_decisions / sentiment.",
        "First NPU run includes graph compile; warmup reduces that bias.",
        "Training (HGB search) stays on CPU — not benchmarked here.",
    ]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[bench] wrote {OUT_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
