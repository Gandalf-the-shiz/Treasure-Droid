"""Close the loop: execution acks → forward portfolio → retrain triggers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXEC_LOG = REPO / "data" / "trading" / "execution_log.jsonl"
FORWARD_BOOK = REPO / "data" / "trading" / "forward_portfolio.json"
TRIGGERS_PATH = REPO / "data" / "learning" / "retrain_triggers.json"
MANIFEST_PATH = REPO / "data" / "trading" / "robinhood_manifest.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def load_forward_book() -> dict:
    book = _load_json(FORWARD_BOOK, {})
    if not book:
        book = {
            "startingCash": 100_000.0,
            "cash": 100_000.0,
            "positions": {},
            "closedTrades": [],
            "fills": [],
            "openedAt": _now(),
        }
    return book


def process_new_acks(since_id: int = 0) -> dict:
    """Ingest execution_log.jsonl fills into forward portfolio."""
    if not EXEC_LOG.exists():
        return {"processed": 0, "message": "no execution log"}

    book = load_forward_book()
    last_idx = int(book.get("lastAckIndex") or 0)
    processed = 0
    lines = EXEC_LOG.read_text(encoding="utf-8").splitlines()

    for i, line in enumerate(lines):
        if i < last_idx:
            continue
        line = line.strip()
        if not line:
            continue
        try:
            ack = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ack.get("status") not in {"filled", "partial"}:
            book["lastAckIndex"] = i + 1
            continue

        sym = str(ack.get("symbol") or _symbol_from_manifest(ack.get("order_id")) or "").upper()
        qty = float(ack.get("filled_qty") or 0)
        notional = float(ack.get("filled_notional") or 0)
        px = float(ack.get("avg_price") or 0)
        if not sym or qty <= 0:
            book["lastAckIndex"] = i + 1
            continue

        pos_side = str(ack.get("position_side") or "long").lower()
        effect = str(ack.get("position_effect") or "open").lower()
        cash_delta = notional if notional > 0 else qty * px

        if effect == "open" and pos_side == "long":
            book["cash"] = round(book.get("cash", 0) - cash_delta, 2)
            book["positions"][sym] = {
                "qty": qty, "avgPx": px or (cash_delta / qty if qty else 0),
                "costBasis": round(cash_delta, 2), "side": "long",
                "openedAt": ack.get("executed_at") or _now(),
            }
        elif effect == "open" and pos_side == "short":
            book["cash"] = round(book.get("cash", 0) + cash_delta, 2)
            book["positions"][sym] = {
                "qty": -abs(qty), "avgPx": px or (cash_delta / qty if qty else 0),
                "costBasis": round(cash_delta, 2), "side": "short",
                "openedAt": ack.get("executed_at") or _now(),
            }
        elif effect == "close" and pos_side == "long":
            pos = book["positions"].pop(sym, {})
            book["cash"] = round(book.get("cash", 0) + cash_delta, 2)
            pnl = round(cash_delta - float(pos.get("costBasis", cash_delta)), 2)
            book["closedTrades"] = (book.get("closedTrades") or [])[-500:] + [{
                "symbol": sym, "pnl": pnl, "side": "long", "closedAt": ack.get("executed_at") or _now(),
            }]
        elif effect == "close" and pos_side == "short":
            pos = book["positions"].pop(sym, {})
            book["cash"] = round(book.get("cash", 0) - cash_delta, 2)
            pnl = round(float(pos.get("costBasis", 0)) - cash_delta, 2)
            book["closedTrades"] = (book.get("closedTrades") or [])[-500:] + [{
                "symbol": sym, "pnl": pnl, "side": "short", "closedAt": ack.get("executed_at") or _now(),
            }]
        else:
            # Legacy buy/sell without metadata
            side = str(ack.get("side") or "buy").lower()
            if side == "sell":
                pos = book["positions"].pop(sym, {})
                book["cash"] = round(book.get("cash", 0) + cash_delta, 2)
                pnl = round(cash_delta - float(pos.get("costBasis", cash_delta)), 2)
                book["closedTrades"] = (book.get("closedTrades") or [])[-500:] + [{
                    "symbol": sym, "pnl": pnl, "side": pos.get("side", "long"),
                    "closedAt": ack.get("executed_at") or _now(),
                }]
            else:
                book["cash"] = round(book.get("cash", 0) - cash_delta, 2)
                book["positions"][sym] = {
                    "qty": qty, "avgPx": px, "costBasis": round(cash_delta, 2),
                    "side": "long", "openedAt": ack.get("executed_at") or _now(),
                }

        book["fills"] = (book.get("fills") or [])[-1000:] + [ack]
        book["lastAckIndex"] = i + 1
        processed += 1

    book["updatedAt"] = _now()
    _save_json(FORWARD_BOOK, book)
    triggers = _evaluate_retrain_triggers(book)
    _save_json(TRIGGERS_PATH, triggers)
    return {"processed": processed, "forwardEquity": _equity(book), "triggers": triggers}


def _symbol_from_manifest(order_id: str) -> str | None:
    if not order_id or not MANIFEST_PATH.exists():
        return None
    try:
        m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        for o in m.get("orders") or []:
            if o.get("order_id") == order_id:
                return o.get("symbol")
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _equity(book: dict) -> float:
    cash = float(book.get("cash") or 0)
    invested = sum(
        float(p.get("qty", 0)) * float(p.get("avgPx", 0))
        for p in (book.get("positions") or {}).values()
    )
    return round(cash + invested, 2)


def _evaluate_retrain_triggers(book: dict) -> dict:
    """Suggest retrain when forward execution book degrades."""
    start = float(book.get("startingCash") or 100_000)
    eq = _equity(book)
    ret_pct = (eq / start - 1.0) * 100 if start else 0.0
    closed = book.get("closedTrades") or []
    wins = sum(1 for t in closed if float(t.get("pnl") or 0) > 0)
    n = len(closed)
    win_rate = wins / n if n else 0.0

    trigger_predictor = ret_pct < -2.0 and n >= 10
    trigger_investor = ret_pct < -1.0 and win_rate < 0.4 and n >= 15

    return {
        "generatedAt": _now(),
        "forwardReturnPct": round(ret_pct, 3),
        "nClosedTrades": n,
        "winRate": round(win_rate, 3),
        "triggerPredictorRetrain": trigger_predictor,
        "triggerInvestorRetrain": trigger_investor,
        "message": (
            "forward book suggests predictor retrain" if trigger_predictor else
            "forward book suggests investor retrain" if trigger_investor else
            "forward book stable"
        ),
    }


def on_ack(report: dict) -> dict:
    """Called immediately after each ack is logged."""
    sym = report.get("symbol")
    if sym:
        report = dict(report)
        report["symbol"] = str(sym).upper()
    line = json.dumps(report)
    EXEC_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(EXEC_LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return process_new_acks()


def run() -> dict:
    return process_new_acks()
