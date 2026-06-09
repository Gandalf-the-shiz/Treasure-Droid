"""Local Nostradamus server.

Serves the static front-end + a small JSON API on top of the existing
artefacts. Run:

    python scripts/serve.py            # http://127.0.0.1:8000
    python scripts/serve.py --port 4173

Endpoints
---------
GET  /                       static front-end (index.html)
GET  /api/health             { ok, version, decisions: {...} }
GET  /api/decisions          returns data/investor_v3/decisions.json
POST /api/retrain            launches train-investor-v3.py in background
GET  /api/retrain/status     { state, started_at, finished_at, returncode, log_tail }
GET  /api/trading/manifest   Robinhood Agents swing manifest
GET  /api/daytrade/manifest  Intraday aggressive manifest
GET  /api/reasoning/strategy Paper-trading reasoning agent strategy
GET  /api/brain/schedule     Market-aware scheduler state
POST /api/trading/ack        Record fill from external broker
POST /api/orchestrator/run   Full prep pipeline
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
LIVE_ROOT = Path(os.getenv("NOSTRA_LIVE_ROOT", r"C:\Users\nicho\nostradamus-live"))
sys.path.insert(0, str(ROOT / "scripts"))

DECISIONS_PATH = ROOT / "data" / "investor_v3" / "decisions.json"
TRADING_MANIFEST = ROOT / "data" / "trading" / "robinhood_manifest.json"
TRADING_SIGNALS = ROOT / "data" / "trading" / "signals.json"
CONGRESS_SIGNALS = ROOT / "data" / "congress" / "signals_by_symbol.json"
CONGRESS_LEADERBOARD = ROOT / "data" / "congress" / "leaderboard.json"
CONGRESS_NOTABLE = ROOT / "data" / "congress" / "notable_trades.json"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
VERSION = "0.2.0"
MODEL_PATH = ROOT / "models" / "v3" / "investor" / "policy.joblib"
SENTIMENT_PATH = ROOT / "data" / "sentiment" / "per_symbol.json"
HIST_MANIFEST = ROOT / "data" / "historical" / "manifest.json"

# ── Default training command. Mirrors the canonical config we backtest with.
TRAIN_CMD = [
    sys.executable,
    str(ROOT / "scripts" / "train-investor-v3.py"),
    "--top-k", "5",
    "--max-position-frac", "0.20",
    "--max-gross-exposure", "0.90",
    "--kelly-scale", "0.5",
    "--cost-bps", "5",
    "--slippage-bps", "10",
    "--min-proba", "0.60",
    "--min-pred-ret", "0.020",
    "--min-price", "5",
    "--min-adv", "1000000",
    "--min-vol-20", "0.01",
    "--max-daily-ret", "0.20",
    "--policy-mode", "edge",
]

# ── In-memory job state. Single-slot — only one retrain at a time.
_job_lock = threading.Lock()
_job: dict = {
    "state": "idle",            # idle | running | done | failed
    "started_at": None,
    "finished_at": None,
    "returncode": None,
    "log_path": None,
    "pid": None,
}


def _file_meta(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _tail(path: Path, n: int = 40) -> list[str]:
    if not path or not Path(path).exists():
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        return [ln.rstrip("\n") for ln in lines[-n:]]
    except OSError:
        return []


def _run_training(log_path: Path) -> None:
    """Run the trainer as a subprocess and update _job state when done."""
    try:
        with open(log_path, "w", encoding="utf-8") as logf:
            logf.write(f"# nostradamus retrain @ {datetime.now(timezone.utc).isoformat()}\n")
            logf.write(f"# cmd: {' '.join(TRAIN_CMD)}\n\n")
            logf.flush()
            proc = subprocess.Popen(
                TRAIN_CMD,
                cwd=str(ROOT),
                stdout=logf,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with _job_lock:
                _job["pid"] = proc.pid
            rc = proc.wait()
        with _job_lock:
            _job["state"] = "done" if rc == 0 else "failed"
            _job["returncode"] = rc
            _job["finished_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:  # pragma: no cover
        with _job_lock:
            _job["state"] = "failed"
            _job["returncode"] = -1
            _job["finished_at"] = datetime.now(timezone.utc).isoformat()
            _job["error"] = str(exc)


app = FastAPI(title="Treasure Droid local server", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Public read-only guard ────────────────────────────────────────────────
# treasure-droid.com is public to VIEW, but action/mutating endpoints must not
# be triggerable from the internet. Requests arriving via Cloudflare carry
# CF-* headers (set at Cloudflare's edge, not spoofable by the client, and the
# app has no inbound port — the tunnel is the only public path). Local calls
# (autonomous loops, owner on the box) have no CF headers and are unrestricted.
# An optional owner token (X-TD-Token == TD_ADMIN_TOKEN) bypasses the block so
# you can act remotely later if you set that secret.
_PUBLIC_READONLY = os.getenv("TD_PUBLIC_READONLY", "true").lower() in {"1", "true", "yes"}
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _is_public_request(request) -> bool:
    h = request.headers
    return bool(h.get("cf-connecting-ip") or h.get("cf-ray"))


@app.middleware("http")
async def public_readonly_guard(request, call_next):
    if _PUBLIC_READONLY and request.method in _WRITE_METHODS and _is_public_request(request):
        try:
            from app_secrets import get_secret
            admin = get_secret("TD_ADMIN_TOKEN")
        except Exception:
            admin = None
        if not (admin and request.headers.get("x-td-token") == admin):
            return JSONResponse(
                status_code=403,
                content={
                    "error": "read_only_public",
                    "detail": "Actions are disabled on the public site. Use the local machine (or set TD_ADMIN_TOKEN).",
                },
            )
    return await call_next(request)


def _last_nightly_log() -> dict:
    """Parse the most recent nightly-*.log to expose pipeline health."""
    logs = sorted(LOG_DIR.glob("nightly-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return {"exists": False}
    p = logs[0]
    out: dict = {
        "exists": True,
        "path": p.name,
        "modified_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
    }
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    # Parse our own marker lines written by nightly.ps1
    for line in text.splitlines():
        if line.startswith("# fetch exit code:"):
            try: out["fetch_rc"] = int(line.split(":", 1)[1].strip())
            except Exception: pass
        elif line.startswith("# train exit code:"):
            try: out["train_rc"] = int(line.split(":", 1)[1].strip())
            except Exception: pass
        elif line.startswith("# enrich exit code:"):
            try: out["enrich_rc"] = int(line.split(":", 1)[1].strip())
            except Exception: pass
    return out


def _last_bar_date() -> str | None:
    """Read manifest.json to expose the most recent OHLCV bar date."""
    if not HIST_MANIFEST.exists():
        return None
    try:
        m = json.loads(HIST_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # manifest schema varies; try common keys
    for k in ("last_bar_date", "latest_date", "max_date", "as_of", "updated_at"):
        v = m.get(k)
        if isinstance(v, str) and v:
            return v[:10]
    return None


def _pipeline_status() -> dict:
    return {
        "model": _file_meta(MODEL_PATH),
        "sentiment_cache": _file_meta(SENTIMENT_PATH),
        "last_bar_date": _last_bar_date(),
        "last_nightly": _last_nightly_log(),
    }


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "version": VERSION,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "decisions": _file_meta(DECISIONS_PATH),
        "job": {k: v for k, v in _job.items() if k != "log_path"},
        "pipeline": _pipeline_status(),
    }


@app.get("/api/status")
def status():
    """Alias of /api/health['pipeline'] for clients that just want pipeline state."""
    return _pipeline_status()


def _pmp_sane_pnl(x: float) -> bool:
    return -2.0 <= x <= 2.0


def _pmp_bet_analytics(b: dict) -> dict:
    """Edge and expected profit for a binary paper bet (stake in USD at entry price)."""
    stake = float(b.get("stake") or 1.0)
    price = float(b.get("price") or 0.5)
    price = min(max(price, 0.02), 0.98)
    mp = float(b.get("modelProb") or 0.5)
    side = (b.get("side") or "YES").upper()
    if side == "YES":
        p_win = mp
        entry = price
        market_label = "YES"
        alt = "NO"
        p_alt = 1.0 - mp
        alt_price = 1.0 - price
    else:
        p_win = 1.0 - mp
        entry = 1.0 - price
        market_label = "NO"
        alt = "YES"
        p_alt = mp
        alt_price = price
    entry = min(max(entry, 0.02), 0.98)
    win_profit = stake * (1.0 / entry - 1.0)
    lose_profit = -stake
    ev_usd = p_win * win_profit + (1.0 - p_win) * lose_profit
    edge = p_win - entry
    choice = (
        f"Oracle favors {market_label} ({p_win:.1%} true prob) vs market {entry:.1%} implied. "
        f"Alternative {alt} is {p_alt:.1%} model / {alt_price:.1%} market."
    )
    if edge > 0.02:
        rationale = (
            f"Positive edge (+{edge:.1%}): model sees {market_label} as underpriced at {entry:.1%}. "
            f"At ${stake:.2f} stake, expected profit ≈ ${ev_usd:.2f} before fees/slippage."
        )
    elif edge < -0.02:
        rationale = (
            f"Negative edge ({edge:.1%}): market prices {market_label} richer than the model. "
            f"Paper book may be exploratory; expected value ≈ ${ev_usd:.2f}."
        )
    else:
        rationale = (
            f"Near fair value (edge {edge:+.1%}). Expected profit ≈ ${ev_usd:.2f} on ${stake:.2f} stake."
        )
    return {
        "edge": round(edge, 4),
        "expectedProfitUsd": round(ev_usd, 3),
        "expectedProfitPerDollar": round(ev_usd / max(stake, 0.01), 4),
        "choiceSummary": choice,
        "explanation": rationale,
        "impliedProb": round(entry, 4),
        "modelWinProb": round(p_win, 4),
    }


def _pmp_position_row(b: dict, *, mark_unrealized: float | None = None) -> dict:
    stake = float(b.get("stake") or 1.0)
    price = float(b.get("price") or 0.5)
    price = min(max(price, 0.02), 0.98)
    mp = float(b.get("modelProb") or 0.5)
    side = (b.get("side") or "YES").upper()
    analytics = _pmp_bet_analytics(b)
    row = {
        "id": b.get("id"),
        "exchange": b.get("exchange"),
        "ticker": b.get("ticker"),
        "question": (b.get("question") or b.get("ticker") or "")[:160],
        "side": side,
        "price": round(price, 4),
        "modelProb": round(mp, 4),
        "stakeUsd": round(stake, 2),
        "status": b.get("status"),
        "openedAt": b.get("openedAt"),
        "resolvedAt": b.get("resolvedAt"),
        "outcome": b.get("outcome"),
        **analytics,
    }
    if b.get("status") == "resolved":
        pnl = b.get("pnl_per_dollar", 0.0)
        if _pmp_sane_pnl(float(pnl)):
            row["pnlUsd"] = round(float(pnl) * stake, 2)
            row["pnlPerDollar"] = round(float(pnl), 4)
    elif mark_unrealized is not None:
        row["unrealizedUsd"] = round(mark_unrealized, 2)
    return row


@app.get("/api/prediction-markets")
def prediction_markets():
    """Read-only sleeve view of the separate Prediction Market Predictor app.

    Decoupled: reads that app's local data files; never imports its code and never
    fabricates a signal. Override its location with NOSTRA_PMP_ROOT.
    """
    pmp_root = Path(os.getenv("NOSTRA_PMP_ROOT", r"C:\Users\nicho\prediction-market-predictor"))
    data = pmp_root / "data"

    def _ld(name, default):
        try:
            return json.loads((data / name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    bets = _ld("paper_bets.json", [])
    triggers = _ld("alert_triggers.json", [])
    rules = _ld("alert_rules.json", [])
    portfolio_snap = _ld("learning/portfolio.json", {})

    resolved = [b for b in bets if b.get("status") == "resolved"]
    sane_resolved = [b for b in resolved if _pmp_sane_pnl(float(b.get("pnl_per_dollar", 0.0)))]
    n = len(sane_resolved)
    avg_edge = sum(b.get("pnl_per_dollar", 0.0) for b in sane_resolved) / n if n else 0.0
    wins = sum(1 for b in sane_resolved if b.get("pnl_per_dollar", 0.0) > 0)
    brier = None
    if n:
        sq = 0.0
        for b in sane_resolved:
            p_yes = b.get("modelProb", 0.5) if b.get("side") == "YES" else 1.0 - b.get("modelProb", 0.5)
            sq += (p_yes - (1.0 if b.get("outcome") == "YES" else 0.0)) ** 2
        brier = round(sq / n, 4)

    open_bets = [b for b in bets if b.get("status") == "open"]
    open_sorted = sorted(open_bets, key=lambda b: b.get("openedAt") or "", reverse=True)
    recent_resolved = sorted(sane_resolved, key=lambda b: b.get("resolvedAt") or "", reverse=True)[:40]

    available = (pmp_root / "app").exists()
    has_activity = bool(bets or triggers)
    note = ("Prediction app not found (set NOSTRA_PMP_ROOT)." if not available
            else ("Installed but idle — add an LLM key and record/resolve paper bets to populate."
                  if not has_activity else "Forward paper record from the prediction-market sleeve."))

    portfolio = {
        "generatedAt": portfolio_snap.get("generatedAt"),
        "nOpen": portfolio_snap.get("nOpen", len(open_bets)),
        "nResolved": portfolio_snap.get("nResolved", len(sane_resolved)),
        "nMarkedOpen": portfolio_snap.get("nMarkedOpen"),
        "stakeAtRiskUsd": portfolio_snap.get("stakeAtRiskUsd"),
        "realizedUsd": portfolio_snap.get("realizedUsd"),
        "unrealizedUsd": portfolio_snap.get("unrealizedUsd"),
        "totalEquityUsd": portfolio_snap.get("totalEquityUsd"),
        "returnPerStakedDollar": portfolio_snap.get("returnPerStakedDollar"),
        "winRatePct": portfolio_snap.get("winRatePct"),
        "byExchange": portfolio_snap.get("byExchange") or {},
        "note": portfolio_snap.get("note"),
    }

    return {
        "available": available,
        "hasActivity": has_activity,
        "openBets": len(open_bets),
        "resolvedBets": len(sane_resolved),
        "realizedEdgePerDollar": round(avg_edge, 4),
        "winRatePct": round(wins / n * 100, 1) if n else None,
        "brierScore": brier,
        "nAlertRules": len(rules),
        "recentTriggers": [{"question": t.get("question"), "side": t.get("side"),
                            "edge": t.get("edge")} for t in triggers[-8:]],
        "portfolio": portfolio,
        "openPositions": [_pmp_position_row(b) for b in open_sorted[:80]],
        "recentResolved": [_pmp_position_row(b) for b in recent_resolved],
        "positionCounts": {
            "openTotal": len(open_bets),
            "openShown": min(80, len(open_sorted)),
            "resolvedShown": len(recent_resolved),
        },
        "note": note,
    }


@app.get("/api/penny/overview")
def penny_overview():
    """Penny Wolf — sub-$5 momentum desk (separate paper book)."""
    from penny_engine import overview
    return overview()


@app.post("/api/penny/tick")
def penny_tick():
    """Scan sub-$5 universe, rank by heat, paper-trade top names, enforce stops."""
    from penny_engine import tick
    return tick()


@app.get("/api/penny/ml/status")
def penny_ml_status():
    """Penny Wolf ML champion search status + NPU inference readiness."""
    from penny_engine import _penny_ml_status
    return _penny_ml_status()


@app.get("/api/intelligence/status")
def intelligence_status():
    """Unified brain status — mass psychology, insider monitor, forward book."""
    paths = {
        "brain": ROOT / "data" / "intelligence" / "brain_status.json",
        "massPsychology": ROOT / "data" / "mass_psychology" / "ticker_sentiment.json",
        "insiderMonitor": ROOT / "data" / "insider" / "follow_insider_signals.json",
        "forwardBook": ROOT / "data" / "trading" / "forward_portfolio.json",
        "retrainTriggers": ROOT / "data" / "learning" / "retrain_triggers.json",
        "liveChampion": ROOT / "data" / "intelligence" / "live_champion_overlay.json",
        "forwardIc": ROOT / "data" / "accuracy" / "v3_live_ic.json",
    }
    out = {}
    for name, p in paths.items():
        if p.exists():
            try:
                out[name] = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                out[name] = {"error": "parse failed"}
        else:
            out[name] = None
    return out


@app.get("/api/arena/leaderboard")
def arena_leaderboard():
    """Legacy v1 leaderboard (backward compatible)."""
    p = ROOT / "data" / "trader_arena" / "v1" / "leaderboard.json"
    if not p.exists():
        p = ROOT / "data" / "trader_arena" / "leaderboard.json"
    if not p.exists():
        raise HTTPException(404, "arena not run yet — POST /api/arena/pulse or wait for loop")
    return json.loads(p.read_text(encoding="utf-8"))


def _arena_versions() -> list[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.arena.paths import list_versions
    return list_versions()


def _check_arena_version(version: str) -> None:
    if version not in _arena_versions():
        raise HTTPException(400, f"unknown arena version {version}")


@app.get("/api/arena/versions")
def arena_versions():
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.arena.paths import list_versions, ensure_experiment
    exp = ensure_experiment()
    return {"versions": list_versions(), "experiment": exp}


@app.get("/api/arena/experiment")
def arena_experiment():
    p = ROOT / "data" / "trader_arena" / "experiment.json"
    if not p.exists():
        raise HTTPException(404, "experiment not initialized")
    return json.loads(p.read_text(encoding="utf-8-sig"))


@app.get("/api/arena/operating")
def arena_operating():
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.arena.operating import operating_status
    return operating_status()


@app.get("/api/real-agents")
def real_agents_registry():
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.real_agents import sync_registry
    return sync_registry()


@app.get("/api/stack/overview")
def stack_overview():
    """Single payload for Stack & Edge UI (operating model + live metrics)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.arena.operating import operating_status
    from intelligence.arena.ledger import compare_series

    harvest_path = ROOT / "data" / "trader_arena" / "harvest_latest.json"
    harvest = {}
    if harvest_path.exists():
        try:
            harvest = json.loads(harvest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            harvest = {"error": "harvest_latest unreadable"}

    agents_path = ROOT / "data" / "intelligence" / "real_agents" / "registry.json"
    agents = {}
    if agents_path.exists():
        try:
            agents = json.loads(agents_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            agents = {"error": "registry unreadable"}

    live_path = ROOT / "data" / "predictions_v3" / "live.csv"
    n_live = 0
    if live_path.exists():
        try:
            n_live = max(0, sum(1 for _ in live_path.open(encoding="utf-8")) - 1)
        except OSError:
            pass

    megamind_summary = {}
    for p in (
        ROOT / "data" / "intelligence" / "megamind" / "latest_report.json",
        ROOT / "data" / "intelligence" / "ultimate_model" / "latest_report.json",
    ):
        if p.exists():
            try:
                doc = json.loads(p.read_text(encoding="utf-8-sig"))
                recs = doc.get("recommendations") or []
                megamind_summary = {
                    "generatedAt": doc.get("generatedAt"),
                    "nPending": sum(1 for r in recs if r.get("status") == "proposed"),
                    "nApproved": sum(1 for r in recs if r.get("status") == "approved"),
                    "nImplemented": sum(1 for r in recs if r.get("status") == "implemented"),
                    "status": doc.get("status"),
                }
                break
            except (OSError, json.JSONDecodeError):
                pass

    exp_path = ROOT / "data" / "trader_arena" / "experiment.json"
    experiment = {}
    if exp_path.exists():
        try:
            experiment = json.loads(exp_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "operating": operating_status(),
        "realAgents": agents,
        "compare": compare_series(),
        "harvest": harvest,
        "megamind": megamind_summary,
        "livePanel": {"path": "data/predictions_v3/live.csv", "nSymbols": n_live},
        "experiment": experiment,
    }


@app.get("/api/arena/compare")
def arena_compare():
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.arena.ledger import compare_series
    return compare_series()


@app.post("/api/arena/spawn")
def arena_spawn_new(spec: dict = Body(default_factory=dict)):
    """Spawn new arena v3+ (Megamind policy — never mutates v1/v2)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.arena.spawn import spawn_new_arena
    try:
        return spawn_new_arena(
            version=spec.get("version"),
            label=spec.get("label", ""),
            selection_mode=spec.get("selection_mode", "rank_v2"),
            panel_path=spec.get("panel_path"),
            feed_name=spec.get("feed_name"),
            n_traders=int(spec.get("n_traders") or 100),
            source_recommendation=spec.get("source_recommendation"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/arena/{version}/leaderboard")
def arena_version_leaderboard(version: str):
    _check_arena_version(version)
    p = ROOT / "data" / "trader_arena" / version / "leaderboard.json"
    if not p.exists():
        raise HTTPException(404, f"{version} arena not run yet")
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/api/arena/{version}/traders")
def arena_version_traders(version: str):
    _check_arena_version(version)
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.arena.ledger import ranked_traders
    return {"version": version, "traders": ranked_traders(version)}


@app.get("/api/arena/{version}/trader/{trader_id}")
def arena_trader_detail(version: str, trader_id: str):
    _check_arena_version(version)
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.arena.ledger import trader_detail
    doc = trader_detail(version, trader_id)
    if not doc:
        raise HTTPException(404, "trader not found")
    return doc


@app.get("/api/ultimate-model")
def ultimate_model_report():
    """Alias for Megamind report."""
    return megamind_report()


@app.get("/api/megamind")
def megamind_report():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from intelligence.megamind import public_report
        return public_report()
    except FileNotFoundError:
        raise HTTPException(404, "Megamind not run yet — wait for daily close or run megamind.py --tick")


@app.post("/api/megamind/tick")
def megamind_tick():
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "intelligence" / "megamind.py"), "--tick"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr or proc.stdout or "megamind tick failed")
    return megamind_report()


@app.post("/api/megamind/recommendations/{rec_id}/approve")
def megamind_approve_post(rec_id: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.megamind import approve_recommendation
    try:
        return approve_recommendation(rec_id, source="dashboard")
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/megamind/recommendations/{rec_id}/implemented")
def megamind_implemented_post(rec_id: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.megamind import mark_implemented
    try:
        return mark_implemented(rec_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/megamind/recommendations/{rec_id}/reject")
def megamind_reject_post(rec_id: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.megamind import reject_recommendation
    try:
        return reject_recommendation(rec_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/megamind/approve/{rec_id}")
def megamind_approve_link(rec_id: str, token: str = ""):
    """One-click approve from email (localhost / tunneled dashboard host)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.megamind import approve_recommendation, verify_token
    if not verify_token(rec_id, token):
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:24px'>"
            "<h2>Invalid or missing approval token</h2>"
            "<p>Open the <a href='/#/megamind'>Megamind dashboard</a> to approve.</p></body></html>",
            status_code=403,
        )
    try:
        result = approve_recommendation(rec_id, source="email_link")
    except ValueError as e:
        return HTMLResponse(f"<html><body><h2>Error</h2><p>{e}</p></body></html>", status_code=404)
    launch = result.get("cursorLaunch") or {}
    sdk = launch.get("sdk") or {}
    ide = launch.get("ide") or {}
    return HTMLResponse(
        f"""<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
        <body style="font-family:sans-serif;padding:24px;max-width:720px">
        <h2 style="color:#00c805">Megamind — approved &amp; queued for Cursor</h2>
        <p style="color:#555">Approved from your phone — your PC will run the agent when online.</p>
        <p>Recommendation <code>{rec_id}</code></p>
        <ul>
          <li>Cursor rule active: <code>.cursor/rules/megamind-active-task.mdc</code></li>
          <li>Prompt file: <code>{launch.get('promptPath', 'data/intelligence/megamind/CURRENT_AGENT_PROMPT.md')}</code></li>
          <li>IDE opened: {'yes' if ide.get('opened') else 'no — open repo in Cursor'}</li>
          <li>SDK agent: {'started (' + str(sdk.get('mode', '')) + ')' if sdk.get('sdk') else sdk.get('reason', 'set CURSOR_API_KEY for full auto')}</li>
        </ul>
        <p><strong>In Cursor Agent, paste:</strong></p>
        <blockquote style="background:#f4f4f4;padding:12px;border-radius:8px">
        Implement the Megamind active task (@megamind-active-task.mdc)
        </blockquote>
        <p><a href="/#/megamind">Megamind dashboard</a> · <a href="/#/arena">Arena</a></p>
        </body></html>"""
    )


@app.post("/api/arena/pulse")
def arena_pulse():
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "intelligence" / "trader_arena.py"), "--pulse", "--version", "active"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr or proc.stdout or "arena pulse failed")
    return {"ok": True, "stdout": proc.stdout[-2000:]}


@app.post("/api/intelligence/pulse")
def intelligence_pulse():
    """Run full intelligence brain (scrapers + feedback + forward score)."""
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "intelligence" / "brain.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, "PYTHONPATH": str(ROOT / "scripts")},
    )
    return {"ok": proc.returncode == 0, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-2000:]}


@app.get("/api/decisions")
def decisions():
    if not DECISIONS_PATH.exists():
        raise HTTPException(404, "decisions.json not found — run /api/retrain or the trainer")
    return FileResponse(
        DECISIONS_PATH,
        media_type="application/json",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/api/retrain")
def retrain():
    with _job_lock:
        if _job["state"] == "running":
            raise HTTPException(409, "A retrain job is already running")
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = LOG_DIR / f"retrain-{ts}.log"
        _job.update({
            "state": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "returncode": None,
            "log_path": str(log_path),
            "pid": None,
            "error": None,
        })
    t = threading.Thread(target=_run_training, args=(log_path,), daemon=True)
    t.start()
    return {"state": "running", "log": log_path.name}


@app.get("/api/retrain/status")
def retrain_status():
    with _job_lock:
        snapshot = dict(_job)
    log_path = snapshot.get("log_path")
    snapshot["log_tail"] = _tail(Path(log_path), n=50) if log_path else []
    return snapshot


# ── Bars (OHLCV) lookup from local data/historical/<sector>.json files. ─────

_SYM_INDEX: dict[str, Path] = {}
_SYM_INDEX_MTIME: float = 0.0
_BARS_LOCK = threading.Lock()


def _refresh_symbol_index() -> None:
    """Build (or rebuild) a symbol->sector-file index from data/historical."""
    global _SYM_INDEX, _SYM_INDEX_MTIME
    hist = ROOT / "data" / "historical"
    if not hist.exists():
        _SYM_INDEX = {}
        return
    latest = max((p.stat().st_mtime for p in hist.glob("*.json")), default=0.0)
    if latest == _SYM_INDEX_MTIME and _SYM_INDEX:
        return
    idx: dict[str, Path] = {}
    for fp in hist.glob("*.json"):
        if fp.name == "manifest.json":
            continue
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        stocks = (payload.get("stocks") or {}) if isinstance(payload, dict) else {}
        for sym in stocks.keys():
            idx[sym.upper()] = fp
    _SYM_INDEX = idx
    _SYM_INDEX_MTIME = latest


_LIVE_FETCH_LOCK = threading.Lock()
_LIVE_FETCH_MEMO: dict = {}
_LIVE_FETCH_TTL_S = 300.0  # cache live-fetched bars in-memory for 5 min


def _live_fetch_candles(sym: str, days: int = 400) -> list:
    """Fetch ~1y of daily OHLCV via yfinance for a single symbol.

    On-demand fallback when the symbol is not yet in the local lake, so the
    UI works for any US ticker even before the nightly batch runs. Cached
    in-memory and persisted into data/historical/_live.json.
    """
    now = time.time()
    with _LIVE_FETCH_LOCK:
        memo = _LIVE_FETCH_MEMO.get(sym)
        if memo and (now - memo[0]) < _LIVE_FETCH_TTL_S:
            return memo[1]
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        return []
    try:
        df = yf.Ticker(sym).history(period=f"{max(60, days)}d", interval="1d", auto_adjust=False)
    except Exception:
        return []
    if df is None or df.empty:
        return []
    candles: list = []
    for ts, row in df.iterrows():
        try:
            candles.append({
                "date": ts.strftime("%Y-%m-%d"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row.get("Volume", 0) or 0),
            })
        except (KeyError, ValueError, TypeError):
            continue
    with _LIVE_FETCH_LOCK:
        _LIVE_FETCH_MEMO[sym] = (now, candles)
    # Persist for the lake so future requests are instant and survive restart.
    try:
        live_fp = ROOT / "data" / "historical" / "_live.json"
        live_fp.parent.mkdir(parents=True, exist_ok=True)
        if live_fp.exists():
            try:
                payload = json.loads(live_fp.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {"sector": "_live", "stocks": {}}
        else:
            payload = {"sector": "_live", "stocks": {}}
        payload.setdefault("stocks", {})[sym] = {"candles": candles}
        live_fp.write_text(json.dumps(payload), encoding="utf-8")
        global _SYM_INDEX_MTIME
        _SYM_INDEX[sym] = live_fp
        _SYM_INDEX_MTIME = 0.0  # force rescan on next call
    except OSError:
        pass
    return candles


def _load_candles(sym: str) -> tuple[list, str | None, str]:
    """Return (candles, sector_file, source) where source is 'local' | 'live' | 'none'."""
    with _BARS_LOCK:
        _refresh_symbol_index()
        fp = _SYM_INDEX.get(sym)
    candles: list = []
    sector_file: str | None = None
    if fp is not None:
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            stocks = (payload.get("stocks") or {}) if isinstance(payload, dict) else {}
            candles = (stocks.get(sym) or {}).get("candles") or []
            sector_file = fp.name
        except (OSError, json.JSONDecodeError):
            candles = []
    if candles:
        return candles, sector_file, "local"
    candles = _live_fetch_candles(sym)
    if candles:
        return candles, "_live.json", "live"
    return [], None, "none"


@app.get("/api/bars")
def bars(symbol: str, limit: int = 252):
    """Return daily OHLCV candles for a symbol.

    Query: symbol=AAPL, limit=252 (last N candles; 0 = all).
    Falls back to a live yfinance fetch when the symbol isn't in local cache.
    """
    sym = symbol.strip().upper()
    if not sym or not sym.replace(".", "").replace("-", "").isalnum():
        raise HTTPException(400, "invalid symbol")
    candles, sector_file, source = _load_candles(sym)
    if not candles:
        raise HTTPException(404, f"no bars for {sym}")
    if limit and limit > 0:
        candles = candles[-limit:]
    return {
        "symbol": sym,
        "sector_file": sector_file,
        "source": source,
        "count": len(candles),
        "candles": candles,
    }


@app.get("/api/quote")
def quote(symbol: str):
    """Latest close + day change for a symbol, computed from local bars (or live)."""
    sym = symbol.strip().upper()
    if not sym or not sym.replace(".", "").replace("-", "").isalnum():
        raise HTTPException(400, "invalid symbol")
    candles, _sector_file, source = _load_candles(sym)
    if not candles:
        raise HTTPException(404, f"no quote for {sym}")
    last = candles[-1]
    prev = candles[-2] if len(candles) >= 2 else last
    prev_close = float(prev.get("close") or 0.0)
    last_close = float(last.get("close") or 0.0)
    change = last_close - prev_close
    pct = (change / prev_close * 100.0) if prev_close else 0.0
    return {
        "symbol": sym,
        "source": source,
        "date": last.get("date"),
        "open": last.get("open"),
        "high": last.get("high"),
        "low": last.get("low"),
        "close": last_close,
        "previousClose": prev_close,
        "change": change,
        "changePercent": pct,
        "volume": last.get("volume"),
    }


# ── News + sentiment lookup (Yahoo RSS headlines, FinBERT cache). ───────────

@app.get("/api/news")
def news(symbol: str, max_headlines: int = 6):
    """Recent Yahoo RSS headlines for a symbol, with cached FinBERT scores when available.

    Returns: { symbol, headlines: [{title, published, score?, label?}], sentiment: {...} | null }
    """
    sym = symbol.strip().upper()
    if not sym or not sym.replace(".", "").replace("-", "").isalnum():
        raise HTTPException(400, "invalid symbol")
    # Import lazily so server boot does not pay the cost.
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from enrich_decisions import fetch_headlines  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise HTTPException(500, f"news module unavailable: {exc}")

    headlines = fetch_headlines(sym, max_headlines=max(1, min(max_headlines, 20)))

    # Merge FinBERT cache (per-symbol JSON written by enrich_decisions.py).
    cache: dict = {}
    if SENTIMENT_PATH.exists():
        try:
            cache = json.loads(SENTIMENT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}
    sentiment = cache.get(sym)  # already-aggregated summary if recently enriched
    return {
        "symbol": sym,
        "headlines": headlines,
        "sentiment": sentiment,
    }


# ── Trading / Robinhood Agents handoff ───────────────────────────────────────

@app.get("/api/trading/manifest")
def trading_manifest():
    if not TRADING_MANIFEST.exists():
        raise HTTPException(404, "robinhood_manifest.json missing — run generate_trade_signals.py")
    return FileResponse(TRADING_MANIFEST, media_type="application/json", headers={"Cache-Control": "no-cache"})


@app.get("/api/trading/signals")
def trading_signals():
    if not TRADING_SIGNALS.exists():
        raise HTTPException(404, "signals.json missing — run generate_trade_signals.py")
    return FileResponse(TRADING_SIGNALS, media_type="application/json", headers={"Cache-Control": "no-cache"})


@app.get("/api/trading/config")
def trading_config():
    return {
        "brokerMode": os.getenv("BROKER_MODE", "paper"),
        "dryRun": os.getenv("BROKER_MODE", "paper") in {"paper", "dry_run", "manifest_only"},
        "manifest": _file_meta(TRADING_MANIFEST),
        "maxGrossExposure": float(os.getenv("BROKER_MAX_GROSS_EXPOSURE", "0.90")),
        "maxPositionFrac": float(os.getenv("BROKER_MAX_POSITION_FRAC", "0.20")),
        "minProba": float(os.getenv("BROKER_MIN_PROBA", "0.60")),
        "robinhoodPrep": True,
    }


@app.post("/api/trading/ack")
async def trading_ack(body: dict):
    """Record execution feedback from Robinhood Agents (or manual tester)."""
    from broker.adapter import ExecutionReport, RobinhoodAgentBridge

    order_id = str(body.get("order_id") or "")
    if not order_id:
        raise HTTPException(400, "order_id required")
    report = ExecutionReport(
        order_id=order_id,
        status=str(body.get("status") or "filled"),
        filled_qty=float(body.get("filled_qty") or 0),
        filled_notional=float(body.get("filled_notional") or 0),
        avg_price=float(body["avg_price"]) if body.get("avg_price") is not None else None,
        message=str(body.get("message") or ""),
        broker=str(body.get("broker") or "robinhood_agents"),
    )
    feedback = RobinhoodAgentBridge().record_ack(report)
    return {"ok": True, "recorded": order_id, "feedback": feedback}


@app.post("/api/trading/generate")
def trading_generate():
    """Regenerate Robinhood manifest from latest decisions."""
    log_path = LOG_DIR / f"signals-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_trade_signals.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-500:] or "generate_trade_signals failed")
    return {"ok": True, "manifest": _file_meta(TRADING_MANIFEST)}


@app.get("/api/congress/signals")
def congress_signals():
    if not CONGRESS_SIGNALS.exists():
        raise HTTPException(404, "run fetch-congress-trades.py first")
    return FileResponse(CONGRESS_SIGNALS, media_type="application/json", headers={"Cache-Control": "no-cache"})


@app.get("/api/congress/leaderboard")
def congress_leaderboard():
    if not CONGRESS_LEADERBOARD.exists():
        raise HTTPException(404, "run fetch-congress-trades.py first")
    return FileResponse(CONGRESS_LEADERBOARD, media_type="application/json")


@app.get("/api/congress/notable")
def congress_notable():
    """Recent trades by watchlist politicians (Pelosi, Tuberville, etc.)."""
    if not CONGRESS_NOTABLE.exists():
        raise HTTPException(404, "run fetch-congress-trades.py first")
    return FileResponse(CONGRESS_NOTABLE, media_type="application/json")


@app.get("/api/congress/symbol/{symbol}")
def congress_symbol(symbol: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    from congress_signals import get_symbol_signal

    sig = get_symbol_signal(symbol.upper())
    if not sig:
        raise HTTPException(404, f"no congressional signal for {symbol.upper()}")
    return sig


@app.post("/api/congress/refresh")
def congress_refresh():
    log_path = LOG_DIR / f"congress-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "fetch-congress-trades.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-500:] or "fetch-congress-trades failed")
    return {"ok": True, "signals": _file_meta(CONGRESS_SIGNALS)}


@app.get("/api/learning/status")
def learning_status():
    path = ROOT / "data" / "learning" / "harness_state.json"
    if not path.exists():
        return {"phase": "idle", "message": "run learning_harness.py"}
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


REASONING_STRATEGY = ROOT / "data" / "reasoning" / "strategy.json"
REASONING_JOURNAL = ROOT / "data" / "reasoning" / "journal.jsonl"
DAYTRADE_MANIFEST = ROOT / "data" / "trading" / "daytrade_manifest.json"
BRAIN_SCHEDULE = ROOT / "data" / "learning" / "schedule.json"


@app.get("/api/reasoning/strategy")
def reasoning_strategy():
    if not REASONING_STRATEGY.exists():
        raise HTTPException(404, "run reasoning_agent.py --tick first")
    return JSONResponse(json.loads(REASONING_STRATEGY.read_text(encoding="utf-8")))


@app.get("/api/reasoning/journal")
def reasoning_journal(limit: int = 30):
    if not REASONING_JOURNAL.exists():
        return {"entries": []}
    lines = REASONING_JOURNAL.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for ln in lines[-max(1, min(limit, 200)) :]:
        try:
            entries.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return {"entries": entries}


@app.post("/api/reasoning/tick")
def reasoning_tick():
    log_path = LOG_DIR / f"reasoning-api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "reasoning_agent.py"), "--tick"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-500:] or "reasoning_agent failed")
    return {"ok": True, "strategy": _file_meta(REASONING_STRATEGY)}


@app.get("/api/daytrade/manifest")
def daytrade_manifest():
    if not DAYTRADE_MANIFEST.exists():
        raise HTTPException(404, "run generate_daytrade_signals.py first")
    return FileResponse(DAYTRADE_MANIFEST, media_type="application/json", headers={"Cache-Control": "no-cache"})


@app.post("/api/daytrade/generate")
def daytrade_generate():
    log_path = LOG_DIR / f"daytrade-api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_daytrade_signals.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-500:] or "generate_daytrade_signals failed")
    return {"ok": True, "manifest": _file_meta(DAYTRADE_MANIFEST)}


@app.get("/api/brain/schedule")
def brain_schedule():
    if BRAIN_SCHEDULE.exists():
        return JSONResponse(json.loads(BRAIN_SCHEDULE.read_text(encoding="utf-8")))
    return {"recommendedMode": "idle", "message": "run learning_scheduler.py --tick"}


@app.post("/api/brain/tick")
def brain_tick():
    log_path = LOG_DIR / f"brain-api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "learning_scheduler.py"), "--tick"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-800:] or "scheduler tick failed")
    sched = json.loads(BRAIN_SCHEDULE.read_text(encoding="utf-8")) if BRAIN_SCHEDULE.exists() else {}
    return {"ok": True, "schedule": sched}


@app.post("/api/learning/run")
def learning_run():
    log_path = LOG_DIR / f"harness-api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    skip = os.getenv("SKIP_PREDICTOR_TRAIN", "").lower() in {"1", "true", "yes"}
    cmd = [sys.executable, str(ROOT / "scripts" / "learning_harness.py"), "--once"]
    if skip:
        cmd.append("--skip-predictor")
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-800:] or "learning_harness failed")
    return {"ok": True, "log": log_path.name}


PRED_META = ROOT / "models" / "v3" / "predictor" / "metadata.json"
PRED_CHAMP = ROOT / "models" / "v3" / "predictor" / "metadata_champion.json"
INV_META = ROOT / "models" / "v3" / "investor" / "metadata.json"
INV_SUMMARY = ROOT / "data" / "investor_v3" / "summary.json"
LIVE_PRED = ROOT / "data" / "predictions_v3" / "live.csv"
HARNESS_STATE = ROOT / "data" / "learning" / "harness_state.json"
NPU_STATUS = ROOT / "data" / "learning" / "npu_status.json"


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _health_check(check_id: str, label: str, ok: bool, detail: str, **extra) -> dict:
    return {"id": check_id, "label": label, "ok": ok, "detail": detail, **extra}


@app.get("/api/models/overview")
def models_overview():
    """Single-pane metrics for Predictor + Investor + pipeline health."""
    pred = _read_json(PRED_META) or {}
    champ = _read_json(PRED_CHAMP) or pred
    inv_meta = _read_json(INV_META) or {}
    inv_sum = _read_json(INV_SUMMARY) or inv_meta.get("summary") or {}
    pt = (pred.get("metrics") or {}).get("test") or {}
    ct = (champ.get("metrics") or {}).get("test") or pt
    harness = _read_json(HARNESS_STATE) or {}
    npu = _read_json(NPU_STATUS) or {}
    sched = _read_json(BRAIN_SCHEDULE) if BRAIN_SCHEDULE.exists() else {}
    hist = _read_json(HIST_MANIFEST) or {}

    hist_ok = bool(hist.get("totalTickers", 0) > 1000)
    live_ok = LIVE_PRED.exists() and LIVE_PRED.stat().st_size > 100
    dec_ok = DECISIONS_PATH.exists()
    swing_ok = TRADING_MANIFEST.exists()
    day_ok = DAYTRADE_MANIFEST.exists()
    reason_ok = REASONING_STRATEGY.exists()

    checks = [
        _health_check("historical", "Historical OHLCV", hist_ok,
                      f"{hist.get('totalTickers', 0):,} tickers, {hist.get('totalDataPoints', 0):,} bars"),
        _health_check("live_predictions", "Live ML inference", live_ok,
                      "live.csv ready" if live_ok else "run generate_live_predictions.py"),
        _health_check("investor_decisions", "Investor decisions", dec_ok,
                      _file_meta(DECISIONS_PATH).get("modified_at", "missing")),
        _health_check("swing_manifest", "Swing Robinhood manifest", swing_ok,
                      _file_meta(TRADING_MANIFEST).get("modified_at", "missing")),
        _health_check("daytrade_manifest", "Daytrade manifest", day_ok,
                      _file_meta(DAYTRADE_MANIFEST).get("modified_at", "missing")),
        _health_check("reasoning_agent", "Reasoning agent", reason_ok,
                      _file_meta(REASONING_STRATEGY).get("modified_at", "missing")),
        _health_check("continuous_brain", "Scheduler / brain",
                      bool(sched.get("recommendedMode")),
                      sched.get("recommendedMode", "idle")),
        _health_check("npu_runtime", "NPU / ONNX runtime", True,
                      (lambda p: f"{p} ({'accelerated' if p not in ('CPUExecutionProvider', 'AzureExecutionProvider') else 'CPU fallback'})")(
                          npu.get("primary", "CPUExecutionProvider"))),
    ]

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "predictor": {
            "version": pred.get("version"),
            "trainedAt": pred.get("trained_at"),
            "features": pred.get("feature_count"),
            "test": {
                "accuracy": pt.get("accuracy"),
                "auc": pt.get("auc"),
                "f1": pt.get("f1"),
                "regMae": pt.get("reg_mae"),
                "n": pt.get("n"),
            },
            "champion": {
                "accuracy": ct.get("accuracy"),
                "auc": ct.get("auc"),
            },
        },
        "investor": {
            "version": inv_meta.get("version"),
            "trainedAt": inv_meta.get("trained_at"),
            "totalReturnPct": inv_sum.get("total_return_pct"),
            "sharpe": inv_sum.get("annualized_sharpe"),
            "maxDrawdownPct": inv_sum.get("max_drawdown_pct"),
            "winRatePct": inv_sum.get("win_rate_pct"),
            "trades": inv_sum.get("trades"),
        },
        "pipeline": {
            "harnessPhase": harness.get("phase"),
            "harnessMode": harness.get("mode"),
            "schedule": sched,
            "npu": npu,
            "historical": {
                "tickers": hist.get("totalTickers"),
                "lastIncremental": hist.get("lastIncrementalFetch"),
            },
        },
        "healthChecks": checks,
        "healthScore": round(100 * sum(1 for c in checks if c["ok"]) / max(len(checks), 1)),
    }


V2_META = ROOT / "models" / "v2" / "metadata.json"
V2_PREV = ROOT / "models" / "v2" / "metadata_prev.json"
ACCURACY_LOG = ROOT / "data" / "accuracy" / "accuracy-log.json"
PAPER_SUMMARY = ROOT / "data" / "paper_agent" / "summary.json"
PROMO_HISTORY = ROOT / "data" / "learning" / "promotion-history.json"
REASON_PORTFOLIO = ROOT / "data" / "reasoning" / "paper_portfolio.json"


def _forward_truth() -> dict:
    """Mega Yacht scoreboard — forward paper + IC + honest eval (gate-trusted)."""
    readiness = _read_json(LIVE_ROOT / "data" / "gate" / "readiness.json") or {}
    honest = _read_json(LIVE_ROOT / "reports" / "honest_eval.json") or {}
    ic = _read_json(LIVE_ROOT / "data" / "accuracy" / "v3_live_ic.json") or {}
    if not ic.get("n_days") and not ic.get("mean_ic"):
        ic = _read_json(ROOT / "data" / "accuracy" / "v3_live_ic.json") or ic
    gate = _read_json(LIVE_ROOT / "config" / "live_policy.json") or {}
    gpol = (gate.get("gate") or {})
    paper = readiness.get("paperSummary") or {}
    verdict = honest.get("verdict") or {}
    tt_block = honest.get("test_tradeable") or {}
    tt_spread = (tt_block.get("quantile_spread_edge") or {}).get("top_minus_bottom_mean")
    alpha_ic = _read_json(ROOT / "data" / "accuracy" / "alpha_ic.json") or {}
    alpha_blend = alpha_ic.get("blended_neutralized") or {}
    alpha_spread = alpha_blend.get("mean_quintile_spread")
    alpha_icir = alpha_blend.get("icir")
    n_days = ic.get("n_days") or ic.get("nDays") or 0
    mean_ic = ic.get("mean_ic") if ic.get("mean_ic") is not None else ic.get("meanRankIc")
    sharpe = paper.get("sharpe")
    ret = paper.get("totalReturnPct")
    marks = paper.get("nMarks") or 0

    def _bar(val, target, higher=True):
        if val is None or target is None:
            return 0.0
        if higher:
            return min(1.0, max(0.0, float(val) / float(target))) if target else 0.0
        return min(1.0, max(0.0, 1.0 - float(val) / float(target))) if target else 0.0

    metrics = [
        {
            "id": "edge_proven",
            "label": "Mad Scientist eval edge",
            "value": verdict.get("edge_proven"),
            "display": "proven" if verdict.get("edge_proven") else "experimenting",
            "ok": bool(verdict.get("edge_proven")),
            "progress": 1.0 if verdict.get("edge_proven") else 0.0,
        },
        {
            "id": "paper_sharpe",
            "label": "Forward paper Sharpe",
            "value": sharpe,
            "display": f"{sharpe:.2f}" if sharpe is not None else "—",
            "target": gpol.get("min_paper_sharpe", 0.5),
            "ok": sharpe is not None and sharpe >= gpol.get("min_paper_sharpe", 0.5),
            "progress": _bar(sharpe, gpol.get("min_paper_sharpe", 0.5)),
        },
        {
            "id": "paper_return",
            "label": "Forward paper return %",
            "value": ret,
            "display": f"{ret:+.2f}%" if ret is not None else "—",
            "target": gpol.get("min_paper_return_pct", 1.0),
            "ok": ret is not None and ret >= gpol.get("min_paper_return_pct", 1.0),
            "progress": _bar(ret, gpol.get("min_paper_return_pct", 1.0)),
        },
        {
            "id": "live_ic",
            "label": "Live forward IC",
            "value": mean_ic,
            "display": f"{mean_ic:.4f} ({n_days}d)" if mean_ic is not None else f"— ({n_days}d)",
            "target": gpol.get("min_live_rank_ic", 0.01),
            "ok": n_days >= gpol.get("min_live_days", 20) and mean_ic is not None and mean_ic >= gpol.get("min_live_rank_ic", 0.01),
            "progress": min(1.0, n_days / max(1, gpol.get("min_live_days", 20))) * _bar(mean_ic, gpol.get("min_live_rank_ic", 0.01)),
        },
        {
            "id": "tradeable_spread",
            "label": "Tradeable quintile spread (raw)",
            "value": tt_spread,
            "display": f"{tt_spread:.5f}" if tt_spread is not None else "—",
            "ok": (tt_spread or 0) > 0,
            "progress": 1.0 if (tt_spread or 0) > 0 else 0.0,
        },
        {
            "id": "alpha_spread",
            "label": "Blended alpha spread (neutralized)",
            "value": alpha_spread,
            "display": f"{alpha_spread:+.5f}" if alpha_spread is not None else "—",
            "ok": (alpha_spread or 0) > 0,
            "progress": 1.0 if (alpha_spread or 0) > 0 else 0.0,
        },
        {
            "id": "alpha_icir",
            "label": "Blended alpha ICIR",
            "value": alpha_icir,
            "display": f"{alpha_icir:.3f}" if alpha_icir is not None else "—",
            "target": 0.30,
            "ok": (alpha_icir or 0) >= 0.30,
            "progress": min(1.0, (alpha_icir or 0) / 0.30) if alpha_icir is not None else 0.0,
        },
    ]
    explain = {
        "edge_proven": "The master gate. Out-of-sample, do our top-ranked stocks actually beat our bottom-ranked ones on tradeable names? 'Proven' = the mad experiment worked.",
        "paper_sharpe": "Return per unit of risk on the forward paper book. 0.5 is the floor to consider real money, 1+ is good, 2+ is elite. Forward — not a backtest.",
        "paper_return": "Actual P&L of the simulated book trading forward on real prices with fake money. The live experiment scoreboard.",
        "live_ic": "Information Coefficient — how well today's rankings line up with tomorrow's moves, measured live. ~0.02+ sustained is genuinely valuable; needs 20+ days to count.",
        "tradeable_spread": "Raw model only: top-bucket minus bottom-bucket return on liquid stocks. Negative means the raw signal isn't tradeable alone (its edge hides in microcaps).",
        "alpha_spread": "After blending uncorrelated sleeves and neutralizing sector/size: top minus bottom on tradeable names. Positive = the engine makes a genuinely tradeable edge.",
        "alpha_icir": "Consistency of the blended edge (mean IC ÷ its wobble). Higher = the edge shows up reliably, not by luck. 0.3+ is the target.",
    }
    for m in metrics:
        m["explain"] = explain.get(m["id"], "")
        m["kind"] = "forward" if m["id"] in {"paper_sharpe", "paper_return", "live_ic"} else "research"

    live_ok = bool(readiness.get("liveTradingPermitted"))
    return {
        "liveTradingPermitted": live_ok,
        "reasons": readiness.get("reasons") or [],
        "metrics": metrics,
        "paperMarks": marks,
        "plan": "docs/MEGA_YACHT.md",
    }


def _mad_scientist_loop_state() -> dict:
    st = _read_json(ROOT / "data" / "intelligence" / "historical" / "loop_state.json") or {}
    if not st:
        return {"ok": False, "status": "idle"}
    return {
        "ok": True,
        "status": st.get("status", "running"),
        "cycle": st.get("cycle"),
        "lastProfile": st.get("lastProfile"),
        "updatedAt": st.get("updatedAt"),
        "champions": (st.get("champions") or [])[:5],
        "lastResult": st.get("lastResult"),
    }


def _mad_scientist_lab() -> dict:
    """Mad Scientist Lab — 8yr train / 2yr historical walk-forward results."""
    doc = _read_json(ROOT / "data" / "intelligence" / "historical" / "lab_results.json") or {}
    meta = _read_json(ROOT / "data" / "intelligence" / "historical" / "panel_meta.json") or {}
    loop = _mad_scientist_loop_state()
    if not doc.get("ok"):
        return {"ok": False, "message": doc.get("message") or "lab not run yet", "loop": loop}
    lb = doc.get("leaderboard") or []
    surv = doc.get("survivors") or []
    return {
        "ok": True,
        "generatedAt": doc.get("generatedAt"),
        "mantra": "mad_scientist",
        "verdict": doc.get("verdict"),
        "caveat": doc.get("caveat"),
        "method": doc.get("method"),
        "window": doc.get("window"),
        "panel": doc.get("panel") or meta,
        "nGenomes": doc.get("nGenomes"),
        "nScored": doc.get("nScored"),
        "topHeldUp": doc.get("topSelectionHeldUp"),
        "leaderboard": lb[:10],
        "nSurvivors": len(surv),
        "bestHoldoutSharpe": lb[0].get("holdSharpe") if lb else None,
        "loop": loop,
    }


def _sleeve_ic_summary() -> dict:
    """Per-sleeve forward + research IC for the Bridge scoreboard."""
    doc = _read_json(ROOT / "data" / "accuracy" / "sleeve_ic.json") or {}
    if not doc.get("ok"):
        return {"ok": False}
    forward = doc.get("forward") or {}
    research = doc.get("research") or {}
    sleeves = []
    names = sorted(set(list((forward.get("by_sleeve") or {}).keys()) + list((research.get("by_sleeve") or {}).keys())))
    for name in names:
        fwd = (forward.get("by_sleeve") or {}).get(name) or {}
        res = (research.get("by_sleeve") or {}).get(name) or {}
        eff_w = (doc.get("effective_weights") or {}).get(name)
        cfg_w = (doc.get("config_weights") or {}).get(name)
        sleeves.append({
            "id": name,
            "label": fwd.get("label") or res.get("label") or name,
            "forwardIc": fwd.get("mean_ic"),
            "forwardIcir": fwd.get("icir"),
            "forwardDays": fwd.get("n_days") or 0,
            "researchIc": res.get("mean_ic"),
            "researchIcir": res.get("icir"),
            "decayed": bool(fwd.get("decayed")),
            "effectiveWeight": eff_w,
            "configWeight": cfg_w,
        })
    return {
        "ok": True,
        "generatedAt": doc.get("generatedAt"),
        "weightMode": doc.get("weight_mode"),
        "weightNotes": doc.get("weight_notes") or [],
        "forwardDays": forward.get("n_days") or 0,
        "minForwardDays": doc.get("min_forward_days") or 5,
        "sleeves": sleeves,
    }


def _alpha_book_summary() -> dict:
    """Compact summary of the market-neutral alpha book for the dashboard."""
    book = _read_json(ROOT / "data" / "intelligence" / "alpha" / "book.json") or {}
    if not book.get("ok"):
        return {"ok": False}
    b = book.get("book") or {}
    return {
        "ok": True,
        "generatedAt": book.get("generatedAt"),
        "universe": book.get("universe"),
        "sleeves": list((book.get("sleevesUsed") or {}).keys()),
        "weightMode": book.get("weightMode"),
        "nLong": b.get("nLong"),
        "nShort": b.get("nShort"),
        "grossExposure": b.get("grossExposure"),
        "netExposure": b.get("netExposure"),
    }


def _alpaca_paper_cached() -> dict:
    """Last known Alpaca paper execution state (no network)."""
    st = _read_json(ROOT / "data" / "intelligence" / "alpha" / "alpaca_state.json") or {}
    return {
        "mode": st.get("mode"),
        "placed": st.get("placed"),
        "nLong": st.get("nLong"),
        "nShort": st.get("nShort"),
        "grossLong": st.get("grossLong"),
        "grossShort": st.get("grossShort"),
        "netExposure": st.get("netExposure"),
        "generatedAt": st.get("generatedAt"),
    }


@app.get("/api/fleet")
def fleet_summary():
    """The crew: all forward-paper agents with equity, return, positions, status."""
    summ = _read_json(ROOT / "data" / "fleet" / "summary.json") or {"ok": False}
    reg = _read_json(ROOT / "data" / "fleet" / "registry.json") or {}
    blurbs = {a["id"]: {"blurb": a.get("blurb"), "status": a.get("status")} for a in (reg.get("agents") or [])}
    for a in (summ.get("agents") or []):
        meta = blurbs.get(a.get("id"), {})
        a["blurb"] = meta.get("blurb")
        a["status"] = meta.get("status", a.get("status"))
    return summ


@app.get("/api/fleet/agent/{agent_id}")
def fleet_agent(agent_id: str):
    """One agent's documented book: positions + reasoning, equity curve, recent trades."""
    base = ROOT / "data" / "fleet" / "agents" / agent_id
    today = _read_json(base / "today.json") or {}
    equity = _read_json(base / "equity.json") or []
    reg = _read_json(ROOT / "data" / "fleet" / "registry.json") or {}
    meta = next((a for a in (reg.get("agents") or []) if a.get("id") == agent_id), {})
    trades = []
    tp = base / "trades.jsonl"
    if tp.exists():
        try:
            lines = tp.read_text(encoding="utf-8").strip().splitlines()
            trades = [json.loads(ln) for ln in lines[-60:] if ln.strip()][::-1]
        except (OSError, json.JSONDecodeError):
            trades = []
    if not today:
        raise HTTPException(404, f"agent {agent_id} has no forward book yet")
    return {"agent": {"id": agent_id, "name": meta.get("name"), "kind": meta.get("kind"),
                      "status": meta.get("status"), "blurb": meta.get("blurb"), "params": meta.get("params")},
            "today": today, "equityCurve": equity, "trades": trades}


@app.get("/api/walkforward")
def walkforward():
    """Historical walk-forward: genomes selected on the OOS year's first 60%, judged on the held-out tail."""
    return _read_json(ROOT / "data" / "intelligence" / "fleet" / "walkforward.json") or {"ok": False}


@app.get("/api/bridge/top-traders")
def bridge_top_traders(limit: int = 3):
    """Top N traders across fleet forward paper + arena ML genomes."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.bridge.top_traders import top_traders
    return top_traders(limit=max(1, min(limit, 10)))


@app.get("/api/brain/insights")
def brain_insights():
    """Last 30 backtest runs + dev changelog + harness state."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.brain.journal import insights_payload
    return insights_payload()


@app.post("/api/brain/changelog")
def brain_changelog_append(body: dict = Body(default_factory=dict)):
    """Append a dev changelog entry (Cursor agent / manual)."""
    title = (body.get("title") or "").strip()
    summary = (body.get("summary") or "").strip()
    if not title or not summary:
        raise HTTPException(400, "title and summary required")
    sys.path.insert(0, str(ROOT / "scripts"))
    from intelligence.brain.journal import append_dev_change
    entry = append_dev_change(
        title=title,
        summary=summary,
        author=(body.get("author") or "Cursor agent").strip(),
        areas=body.get("areas") or [],
        tags=body.get("tags") or [],
    )
    return {"ok": True, "entry": entry}


@app.get("/api/alpaca/account")
def alpaca_account():
    """Live Alpaca PAPER account snapshot (equity, P&L, positions). Read-only."""
    try:
        import requests
        from app_secrets import get_secret
        key = get_secret("ALPACA_API_KEY")
        sec = get_secret("ALPACA_API_SECRET")
        if not key or not sec:
            return {"ok": False, "reason": "no_keys"}
        h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
        base = "https://paper-api.alpaca.markets"
        acct = requests.get(f"{base}/v2/account", headers=h, timeout=12).json()
        positions = requests.get(f"{base}/v2/positions", headers=h, timeout=12).json()
        equity = float(acct.get("equity") or 0)
        last_equity = float(acct.get("last_equity") or equity)
        npos = len(positions) if isinstance(positions, list) else 0
        long_mv = sum(float(p.get("market_value", 0)) for p in positions if isinstance(p, dict) and float(p.get("qty", 0)) > 0) if isinstance(positions, list) else 0
        short_mv = sum(float(p.get("market_value", 0)) for p in positions if isinstance(p, dict) and float(p.get("qty", 0)) < 0) if isinstance(positions, list) else 0
        upl = sum(float(p.get("unrealized_pl", 0)) for p in positions if isinstance(p, dict)) if isinstance(positions, list) else 0
        return {
            "ok": True,
            "equity": equity,
            "lastEquity": last_equity,
            "dayChangePct": round((equity / last_equity - 1.0) * 100, 3) if last_equity else 0.0,
            "cash": float(acct.get("cash") or 0),
            "buyingPower": float(acct.get("buying_power") or 0),
            "nPositions": npos,
            "longMarketValue": round(long_mv, 2),
            "shortMarketValue": round(short_mv, 2),
            "netExposure": round(long_mv + short_mv, 2),
            "unrealizedPl": round(upl, 2),
            "shortingEnabled": bool(acct.get("shorting_enabled")),
            "status": acct.get("status"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": str(exc)[:160]}


@app.get("/api/command-center")
def command_center():
    """Full breakdown of every ML model feeding predictions, accuracy, and trends."""
    pred = _read_json(PRED_META) or {}
    champ = _read_json(PRED_CHAMP) or pred
    inv_meta = _read_json(INV_META) or {}
    inv_sum = _read_json(INV_SUMMARY) or inv_meta.get("summary") or {}
    v2 = _read_json(V2_META) or {}
    v2_prev = _read_json(V2_PREV) or {}
    acc_log = _read_json(ACCURACY_LOG) or {}
    paper = _read_json(PAPER_SUMMARY) or {}
    reason = _read_json(REASONING_STRATEGY) or {}
    reason_port = _read_json(REASON_PORTFOLIO) or {}
    npu = _read_json(NPU_STATUS) or {}
    sched = _read_json(BRAIN_SCHEDULE) if BRAIN_SCHEDULE.exists() else {}
    harness = _read_json(HARNESS_STATE) or {}

    pt = (pred.get("metrics") or {}).get("test") or {}
    pv = (pred.get("metrics") or {}).get("val") or {}
    ct = (champ.get("metrics") or {}).get("test") or pt

    # V2 live accuracy trend (filter out empty days)
    acc_entries = [
        {"date": e.get("date"), "hitRate": e.get("hitRate"), "mae": e.get("regressionMAE"), "n": e.get("total")}
        for e in (acc_log.get("entries") or [])
        if e.get("hitRate") is not None and (e.get("total") or 0) > 0
    ]

    live_count = 0
    if LIVE_PRED.exists():
        try:
            live_count = max(0, sum(1 for _ in LIVE_PRED.open(encoding="utf-8")) - 1)
        except OSError:
            live_count = 0

    models = [
        {
            "id": "predictor_v3",
            "name": "Predictor v3",
            "role": "Next-day direction + return (core)",
            "architecture": pred.get("architecture", "HGB x5 stacked + isotonic + HGBR head"),
            "status": "champion",
            "features": pred.get("feature_count"),
            "trainedAt": pred.get("trained_at"),
            "metrics": [
                {"label": "Accuracy", "value": pt.get("accuracy"), "fmt": "pct"},
                {"label": "AUC", "value": pt.get("auc"), "fmt": "num3"},
                {"label": "F1", "value": pt.get("f1"), "fmt": "num3"},
                {"label": "Return MAE", "value": pt.get("reg_mae"), "fmt": "num4"},
                {"label": "Brier", "value": pt.get("brier"), "fmt": "num3"},
                {"label": "Test samples", "value": pt.get("n"), "fmt": "int"},
            ],
            "valAccuracy": pv.get("accuracy"),
            "championAuc": ct.get("auc"),
            "liveCount": live_count,
            "retrain": "Weekly (Sunday deep train)",
        },
        {
            "id": "investor_v3",
            "name": "Investor v3",
            "role": "Portfolio allocator (fractional-Kelly)",
            "architecture": inv_meta.get("architecture", "HGBR policy + Kelly allocator"),
            "status": "active",
            "trainedAt": inv_meta.get("trained_at"),
            "metrics": [
                {"label": "Return", "value": inv_sum.get("total_return_pct"), "fmt": "pctRaw"},
                {"label": "Sharpe", "value": inv_sum.get("annualized_sharpe"), "fmt": "num2"},
                {"label": "Win rate", "value": inv_sum.get("win_rate_pct"), "fmt": "pctRaw"},
                {"label": "Max DD", "value": inv_sum.get("max_drawdown_pct"), "fmt": "pctRaw"},
                {"label": "Trades", "value": inv_sum.get("trades"), "fmt": "int"},
                {"label": "Days", "value": inv_sum.get("trading_days"), "fmt": "int"},
            ],
            "retrain": "Daily (post-close)",
        },
        {
            "id": "v2_predictor",
            "name": "V2 Predictor",
            "role": "Browser/CI daily ensemble",
            "architecture": v2.get("architecture", "HGB dual-head"),
            "status": "ci",
            "features": v2.get("featureCount"),
            "trainedAt": v2.get("trainedAt"),
            "metrics": [
                {"label": "Accuracy", "value": (v2.get("testMetrics") or {}).get("accuracy"), "fmt": "pct"},
                {"label": "AUC", "value": (v2.get("testMetrics") or {}).get("auc"), "fmt": "num3"},
                {"label": "F1", "value": (v2.get("testMetrics") or {}).get("f1"), "fmt": "num3"},
                {"label": "Return MAE", "value": (v2.get("testMetrics") or {}).get("reg_mae"), "fmt": "num4"},
                {"label": "Live 7d hit", "value": (acc_log.get("rolling") or {}).get("7day"), "fmt": "pct"},
                {"label": "Live 30d hit", "value": (acc_log.get("rolling") or {}).get("30day"), "fmt": "pct"},
            ],
            "prevAccuracy": (v2_prev.get("testMetrics") or {}).get("accuracy"),
            "retrain": "Weekly + auto-retrain when <53%",
        },
        {
            "id": "paper_agent",
            "name": "Paper Agent",
            "role": "Online SGD trade-taker",
            "architecture": paper.get("model", "SGD logistic v1"),
            "status": "online",
            "trainedAt": paper.get("generatedAt"),
            "metrics": [
                {"label": "Return", "value": paper.get("totalReturnPct"), "fmt": "pctRaw"},
                {"label": "Max DD", "value": paper.get("maxDrawdownPct"), "fmt": "pctRaw"},
                {"label": "Trades", "value": paper.get("tradeCount"), "fmt": "int"},
                {"label": "Early hit", "value": paper.get("preUpdateHitRateEarly5"), "fmt": "pct"},
                {"label": "Late hit", "value": paper.get("preUpdateHitRateLate5"), "fmt": "pct"},
                {"label": "Learn delta", "value": paper.get("onlineLearningDelta"), "fmt": "num3"},
            ],
            "retrain": "Daily online update",
        },
        {
            "id": "reasoning_agent",
            "name": "Reasoning Agent",
            "role": (lambda b: "NPU LLM strategist + paper book" if b == "genai"
                     else "Template strategist + paper book (no LLM)")(reason.get("llmBackend", "template")),
            "architecture": f"LLM ({reason.get('llmBackend', 'template')})",
            "status": "live" if reason else "idle",
            "trainedAt": reason.get("updatedAt"),
            "metrics": [
                {"label": "Watchlist", "value": len(reason.get("watchlist") or []), "fmt": "int"},
                {"label": "Positions", "value": len((reason_port.get("positions") or {})), "fmt": "int"},
                {"label": "Paper cash", "value": reason_port.get("cash"), "fmt": "usd"},
                {"label": "Max pos", "value": reason.get("maxPositions"), "fmt": "int"},
                {"label": "Risk budget", "value": reason.get("riskBudget"), "fmt": "num2"},
            ],
            "narrative": reason.get("narrative"),
            "retrain": "Every 15 min (RTH)",
        },
    ]

    ov = models_overview()

    # App module highlights for command center navigation
    exp_path = ROOT / "data" / "trader_arena" / "experiment.json"
    exp = _read_json(exp_path) or {}
    om = exp.get("operatingModel") or {}
    meg_report = _read_json(ROOT / "data" / "intelligence" / "megamind" / "latest_report.json") or {}
    meg_recs = meg_report.get("recommendations") or []
    meg_pending = sum(1 for r in meg_recs if (r.get("status") or "") in ("pending", "proposed"))
    penny_ml = _read_json(ROOT / "data" / "penny" / "ml" / "search_status.json") or {}

    pmp_root = Path(os.getenv("NOSTRA_PMP_ROOT", r"C:\Users\nicho\prediction-market-predictor"))
    pmp_port = _read_json(pmp_root / "data" / "learning" / "portfolio.json") or {}

    app_modules = [
        {
            "route": "markets",
            "title": "Markets",
            "icon": "◎",
            "tagline": "Live ML-ranked universe",
            "stat": f"{live_count:,} predictions",
            "tone": "ok",
        },
        {
            "route": "fleet",
            "title": "The Fleet",
            "icon": "\U0001f3f4\u200d\u2620\ufe0f",
            "tagline": "Crew of ML agents · forward paper",
            "stat": "Walking forward",
            "tone": "ok",
        },
        {
            "route": "investor",
            "title": "Investor",
            "icon": "◇",
            "tagline": "Kelly allocator book",
            "stat": f"{inv_sum.get('total_return_pct', 0):+.1f}% backtest" if inv_sum.get("total_return_pct") is not None else "Portfolio policy",
            "tone": "ok" if (inv_sum.get("total_return_pct") or 0) > 0 else "muted",
        },
        {
            "route": "arena",
            "title": "Arena",
            "icon": "⚔",
            "tagline": "Evolutionary traders",
            "stat": f"Pulse {', '.join(om.get('pulseVersions') or ['v1','v2','v3'])}" if om else "Trader genomes",
            "tone": "ok",
        },
        {
            "route": "megamind",
            "title": "Megamind",
            "icon": "🧠",
            "tagline": "Meta-agent improvements",
            "stat": f"{meg_pending} pending approvals" if meg_pending else "Watching",
            "tone": "warn" if meg_pending else "ok",
        },
        {
            "route": "predictions",
            "title": "Prophecy Markets",
            "icon": "⊙",
            "tagline": "Kalshi / Polymarket paper",
            "stat": (
                f"${pmp_port.get('totalEquityUsd', 0):,.0f} equity · {pmp_port.get('nOpen', 0)} open"
                if pmp_port.get("nOpen") is not None else "Prediction sleeve"
            ),
            "tone": "ok" if pmp_port.get("totalEquityUsd") else "muted",
        },
        {
            "route": "penny",
            "title": "Penny Wolf",
            "icon": "🐺",
            "tagline": "Sub-$5 momentum desk",
            "stat": (
                f"ML obj {penny_ml.get('bestObjective', 0):.2f}"
                if penny_ml.get("bestObjective") is not None else "Penny scanner"
            ),
            "tone": "ok",
        },
        {
            "route": "trade",
            "title": "Trade",
            "icon": "↗",
            "tagline": "Manifests & signals",
            "stat": "Robinhood prep",
            "tone": "muted",
        },
        {
            "route": "architecture",
            "title": "Stack & Edge",
            "icon": "⬡",
            "tagline": "How it all connects",
            "stat": f"Health {ov.get('healthScore', 0)}/100",
            "tone": "ok" if (ov.get("healthScore") or 0) >= 60 else "warn",
        },
    ]

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "forwardTruth": _forward_truth(),
        "alphaBook": _alpha_book_summary(),
        "sleeveIc": _sleeve_ic_summary(),
        "madScientistLab": _mad_scientist_lab(),
        "alpacaPaper": _alpaca_paper_cached(),
        "models": models,
        "trends": {
            "v2Accuracy": acc_entries,
            "v2Rolling": acc_log.get("rolling") or {},
            "investorEquity": _investor_equity_series(),
        },
        "healthChecks": ov.get("healthChecks", []),
        "healthScore": ov.get("healthScore", 0),
        "pipeline": {
            "harnessPhase": harness.get("phase"),
            "harnessMode": harness.get("mode"),
            "session": sched.get("session"),
            "mode": sched.get("recommendedMode"),
            "npu": npu.get("primary", "CPUExecutionProvider"),
            "npuAvailable": npu.get("available", []),
        },
        "appModules": app_modules,
        "brand": {
            "name": "Treasure Droid",
            "epithet": "Greedy Salvage Droid",
            "motto": "Greedy. Forward. Paper until the edge screams yes.",
        },
    }


def _investor_equity_series(max_points: int = 120) -> list:
    dec = _read_json(DECISIONS_PATH)
    if not dec:
        return []
    curve = dec.get("equity_curve") or []
    if not curve:
        return []
    step = max(1, len(curve) // max_points)
    return [
        {"date": p.get("date"), "equity": p.get("equity")}
        for p in curve[::step]
        if p.get("date") and p.get("date") != "FINAL"
    ]


@app.get("/api/predictions/live")
def predictions_live(limit: int = 100):
    if not LIVE_PRED.exists():
        raise HTTPException(404, "live.csv missing — run generate_live_predictions.py")
    try:
        import pandas as pd

        df = pd.read_csv(LIVE_PRED)
        if df.empty:
            return {"items": [], "count": 0}
        df["edge"] = (df["pred_proba_up"].astype(float) - 0.5) * 2.0 * df["pred_ret"].astype(float).abs()
        df = df.sort_values("edge", ascending=False).head(max(1, min(limit, 500)))
        return {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "count": int(len(df)),
            "items": df.to_dict(orient="records"),
        }
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/pipeline/health")
def pipeline_health():
    ov = models_overview()
    return {"checks": ov["healthChecks"], "healthScore": ov["healthScore"], "generatedAt": ov["generatedAt"]}


@app.post("/api/orchestrator/run")
def orchestrator_run():
    """Run the full prep pipeline (feeds → macro → regime → investor → signals)."""
    log_path = LOG_DIR / f"orchestrator-api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "orchestrator.py"), "--skip-train-predictor"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-800:] or "orchestrator failed")
    return {"ok": True, "log": log_path.name}


# ── Static front-end (mounted last so /api/* wins).
app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="static")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    import uvicorn
    print(f"Nostradamus local server -> http://{args.host}:{args.port}")
    print(f"  static root : {ROOT}")
    print(f"  decisions   : {DECISIONS_PATH}")
    uvicorn.run(
        "scripts.serve:app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
