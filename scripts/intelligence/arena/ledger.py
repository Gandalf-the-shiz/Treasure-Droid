"""Cumulative experiment ledger per arena version."""
from __future__ import annotations

import json
from pathlib import Path

from .paths import EXPERIMENT_PATH, _today, ledger_path


def _default_ledger(version: str) -> dict:
    initial = 50_000
    started = _today()
    if EXPERIMENT_PATH.exists():
        try:
            exp = json.loads(EXPERIMENT_PATH.read_text(encoding="utf-8"))
            initial = float(exp.get("initialEquityUsd") or initial)
            started = (exp.get("startedAt") or started)[:10]
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "version": version,
        "startedAt": started,
        "initialEquityUsd": initial,
        "traders": {},
    }


def _normalize_doc(doc: dict) -> dict:
    traders = doc.get("traders")
    if isinstance(traders, list):
        doc["traders"] = {
            str(x.get("traderId")): x
            for x in traders
            if x.get("traderId") is not None
        }
    elif not isinstance(traders, dict):
        doc["traders"] = {}
    return doc


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return _normalize_doc(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return _default_ledger(path.parent.name)


def _save(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def init_ledger_from_leaderboard(version: str) -> None:
    from .paths import leaderboard_path

    lb_path = leaderboard_path(version)
    if not lb_path.exists():
        return
    lb = json.loads(lb_path.read_text(encoding="utf-8"))
    doc = _load(ledger_path(version))
    day = _today()
    for key in ("top10", "bottom5"):
        for r in lb.get(key) or []:
            tid = str(r.get("traderId"))
            if tid in doc["traders"]:
                continue
            eq = doc["initialEquityUsd"]
            ret = float(r.get("returnPct") or 0)
            doc["traders"][tid] = {
                "traderId": int(r.get("traderId")),
                "family": r.get("family"),
                "cumulativeReturnPct": round(ret, 4),
                "equityUsd": round(eq * (1 + ret / 100), 2),
                "nDays": 1,
                "daily": [{
                    "date": day,
                    "returnPct": ret,
                    "equityAfter": round(eq * (1 + ret / 100), 2),
                    "nTrades": r.get("nTrades", 0),
                    "trades": r.get("trades") or [],
                    "reasoning": r.get("reasoning") or "",
                    "portfolio": r.get("portfolio") or [],
                }],
            }
    _save(ledger_path(version), doc)


def record_pulse(version: str, results: list[dict], genomes: dict[int, dict]) -> dict:
    """Append or replace today's row; compound cumulative return."""
    path = ledger_path(version)
    doc = _load(path)
    day = _today()
    initial = float(doc.get("initialEquityUsd") or 50_000)

    for r in results:
        tid = str(r["traderId"])
        g = genomes.get(int(r["traderId"]), {})
        entry = doc["traders"].setdefault(tid, {
            "traderId": int(r["traderId"]),
            "family": r.get("family") or g.get("family"),
            "cumulativeReturnPct": 0.0,
            "equityUsd": initial,
            "nDays": 0,
            "daily": [],
        })
        daily_row = {
            "date": day,
            "returnPct": float(r.get("returnPct") or 0),
            "nTrades": r.get("nTrades", 0),
            "nLong": r.get("nLong", 0),
            "nShort": r.get("nShort", 0),
            "trades": r.get("trades") or [],
            "reasoning": r.get("reasoning") or "",
            "portfolio": r.get("portfolio") or [],
        }
        # Replace same calendar day if re-pulsed
        entry["daily"] = [d for d in entry["daily"] if d.get("date") != day]
        entry["daily"].append(daily_row)
        entry["daily"].sort(key=lambda x: x.get("date") or "")

        equity = initial
        for d in entry["daily"]:
            equity *= 1.0 + float(d.get("returnPct") or 0) / 100.0
        entry["equityUsd"] = round(equity, 2)
        entry["cumulativeReturnPct"] = round((equity / initial - 1.0) * 100, 4)
        entry["nDays"] = len(entry["daily"])
        entry["family"] = r.get("family") or g.get("family")
        entry["genome"] = {
            k: g.get(k) for k in (
                "family", "min_proba", "min_pred_ret", "short_enabled", "short_frac",
                "top_k", "kelly", "alt_scale", "selection_mode", "contrarian",
            )
        }

    _save(path, doc)
    return doc


def _trader_rows(doc: dict) -> list[dict]:
    traders = doc.get("traders")
    if isinstance(traders, dict):
        return list(traders.values())
    if isinstance(traders, list):
        return traders
    return []


def ranked_traders(version: str) -> list[dict]:
    doc = _load(ledger_path(version))
    rows = _trader_rows(doc)
    rows.sort(key=lambda x: float(x.get("cumulativeReturnPct") or 0), reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def _enrich_trader(entry: dict, initial_equity: float = 50_000) -> dict:
    daily = entry.get("daily") or []
    latest = daily[-1] if daily else {}
    port = latest.get("portfolio") or []
    long_usd = sum(float(p.get("notionalUsd") or 0) for p in port if p.get("side") == "long")
    short_usd = sum(float(p.get("notionalUsd") or 0) for p in port if p.get("side") == "short")
    gross = long_usd + short_usd
    equity = float(entry.get("equityUsd") or initial_equity)
    entry["portfolioLatest"] = port
    entry["portfolioHistory"] = [
        {
            "date": d.get("date"),
            "returnPct": d.get("returnPct"),
            "nTrades": d.get("nTrades"),
            "portfolio": d.get("portfolio") or [],
        }
        for d in daily
    ]
    entry["portfolioSummary"] = {
        "asOfDate": latest.get("date"),
        "nPositions": len(port),
        "nLong": sum(1 for p in port if p.get("side") == "long"),
        "nShort": sum(1 for p in port if p.get("side") == "short"),
        "grossLongUsd": round(long_usd, 2),
        "grossShortUsd": round(short_usd, 2),
        "grossExposureUsd": round(gross, 2),
        "grossExposurePct": round(gross / equity * 100, 2) if equity else 0,
        "netLongUsd": round(long_usd - short_usd, 2),
        "cashImpliedUsd": round(max(equity - gross, 0), 2),
        "startingEquityUsd": initial_equity,
    }
    return entry


def trader_detail(version: str, trader_id: str | int) -> dict | None:
    doc = _load(ledger_path(version))
    traders = doc.get("traders")
    if isinstance(traders, dict):
        entry = traders.get(str(trader_id))
        if entry:
            initial = float(doc.get("initialEquityUsd") or 50_000)
            return _enrich_trader(dict(entry), initial)
    return None


def version_summary(version: str) -> dict:
    rows = ranked_traders(version)
    if not rows:
        return {"version": version, "nTraders": 0}
    cum = [float(r.get("cumulativeReturnPct") or 0) for r in rows]
    import statistics
    return {
        "version": version,
        "nTraders": len(rows),
        "bestCumulativePct": max(cum),
        "medianCumulativePct": round(statistics.median(cum), 4),
        "meanCumulativePct": round(statistics.mean(cum), 4),
        "topTraderId": rows[0].get("traderId"),
    }


def compare_series() -> dict:
    from .paths import list_versions

    vers = list_versions()
    out: dict = {"dates": [], "versions": vers, "versionSummaries": {}, "versionEquityIndexes": {}}
    for v in vers:
        out[v] = []
    dates = set()
    for v in vers:
        doc = _load(ledger_path(v))
        by_date: dict[str, list[float]] = {}
        for t in _trader_rows(doc):
            for d in t.get("daily") or []:
                dt = d.get("date")
                if not dt:
                    continue
                dates.add(dt)
                by_date.setdefault(dt, []).append(float(d.get("returnPct") or 0))
        for dt in sorted(by_date.keys()):
            vals = by_date[dt]
            import statistics
            out[v].append({
                "date": dt,
                "meanDailyReturnPct": round(statistics.mean(vals), 4) if vals else 0,
                "medianDailyReturnPct": round(statistics.median(vals), 4) if vals else 0,
            })
    out["dates"] = sorted(dates)
    for v in vers:
        idx = 100.0
        curve = []
        by_dt = {x["date"]: x["meanDailyReturnPct"] for x in out[v]}
        for dt in out["dates"]:
            idx *= 1.0 + by_dt.get(dt, 0) / 100.0
            curve.append(round(idx, 3))
        out[f"{v}EquityIndex"] = curve
        out["versionEquityIndexes"][v] = curve
    for v in vers:
        out["versionSummaries"][v] = version_summary(v)
    v1s = out["versionSummaries"].get("v1") or version_summary("v1")
    v2s = out["versionSummaries"].get("v2") or version_summary("v2")
    out["v1Summary"] = v1s
    out["v2Summary"] = v2s
    best = max(vers, key=lambda x: (out["versionSummaries"].get(x) or {}).get("meanCumulativePct") or -1e9) if vers else None
    out["leadingVersion"] = best
    out["v2BeatingV1"] = (
        (v2s.get("meanCumulativePct") or 0) > (v1s.get("meanCumulativePct") or 0)
        if v1s.get("nTraders") and v2s.get("nTraders") else None
    )
    return out
