"""Unified top traders for Bridge — fleet forward paper + arena ML genomes."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _fmt_family(fam: str | None) -> str:
    if not fam:
        return "Genome"
    return str(fam).replace("_", " ").title()


def _arena_bio(version: str, entry: dict) -> str:
    g = entry.get("genome") or {}
    family = entry.get("family") or g.get("family") or "genome"
    daily = entry.get("daily") or []
    reasoning = (daily[-1].get("reasoning") or "").strip() if daily else ""
    top_k = g.get("top_k", "?")
    kelly = g.get("kelly", "?")
    mp = g.get("min_proba", "?")
    short = g.get("short_enabled")
    strat = (
        f"Market-neutral { _fmt_family(family) } genome in Arena {version.upper()}. "
        f"Picks top {top_k} names (min proba {mp}, Kelly {kelly}). "
    )
    if short:
        strat += f"Long/short book with {int(float(g.get('short_frac') or 0) * 100)}% short sleeve. "
    else:
        strat += "Long-only conviction sleeve. "
    if reasoning:
        strat += reasoning[:220]
    return strat.strip()


def _fleet_bio(agent: dict, meta: dict) -> str:
    if meta.get("blurb"):
        return str(meta["blurb"])
    params = meta.get("params") or {}
    family = params.get("family") or agent.get("kind") or "genome"
    signal = params.get("signal", "edge")
    origin = meta.get("spawnedBy") or meta.get("origin") or "fleet"
    parts = [
        f"{_fmt_family(family)} forward-paper spawn ({origin.replace('_', ' ')}). ",
        f"Signal: {signal}. ",
    ]
    if params.get("top_k"):
        parts.append(f"Top {params['top_k']} daily · min_proba {params.get('min_proba', '—')}. ")
    status = agent.get("status") or meta.get("status") or "shadow"
    parts.append(f"Status: {status.replace('_', ' ')} — earning forward proof on live panel.")
    return "".join(parts).strip()


def _portfolio_line_arena(ps: dict) -> str:
    if not ps:
        return "No open book snapshot yet."
    nl = ps.get("nLong") or 0
    ns = ps.get("nShort") or 0
    gross = ps.get("grossExposurePct")
    return (
        f"{nl} long / {ns} short · {ps.get('nPositions', 0)} names · "
        f"gross {gross}% of ${ps.get('startingEquityUsd', 50000):,.0f} sim book"
    )


def _portfolio_line_fleet(agent: dict) -> str:
    nl = agent.get("nLong") or 0
    ns = agent.get("nShort") or 0
    nt = agent.get("nTrades") or 0
    np = agent.get("nPositions") or 0
    eq = agent.get("equity")
    eq_s = f"${eq:,.0f}" if eq is not None else "—"
    return f"{nl}L / {ns}S · {np} positions · {nt} trades · equity {eq_s}"


def top_traders(*, limit: int = 3) -> dict:
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    from intelligence.arena.ledger import ranked_traders, trader_detail
    from intelligence.arena.operating import pulse_versions

    candidates: list[dict] = []

    summ = _read(REPO / "data" / "fleet" / "summary.json")
    reg = _read(REPO / "data" / "fleet" / "registry.json")
    meta_by_id = {a["id"]: a for a in (reg.get("agents") or []) if a.get("id")}

    for agent in summ.get("agents") or []:
        ret = agent.get("returnPct")
        if ret is None:
            continue
        aid = agent.get("id")
        meta = meta_by_id.get(aid, {})
        candidates.append({
            "source": "fleet",
            "id": str(aid),
            "name": agent.get("name") or aid,
            "family": (meta.get("params") or {}).get("family") or agent.get("kind") or "genome",
            "scorePct": float(ret),
            "returnPct": float(ret),
            "equityUsd": agent.get("equity"),
            "dayPnl": agent.get("dayPnl"),
            "nDays": None,
            "bio": _fleet_bio(agent, meta),
            "portfolio": _portfolio_line_fleet(agent),
            "performance": {
                "returnPct": float(ret),
                "equityUsd": agent.get("equity"),
                "dayPnl": agent.get("dayPnl"),
                "label": "Forward paper",
            },
            "href": f"#/fleet/{aid}",
            "badge": "Fleet",
        })

    for version in pulse_versions():
        for row in ranked_traders(version)[:20]:
            tid = row.get("traderId")
            if tid is None:
                continue
            ret = row.get("cumulativeReturnPct")
            if ret is None:
                continue
            candidates.append({
                "source": "arena",
                "id": str(tid),
                "version": version,
                "scorePct": float(ret),
                "_row": row,
            })

    candidates.sort(key=lambda c: c.get("scorePct") or -999, reverse=True)
    seen: set[str] = set()
    picked: list[dict] = []
    for c in candidates:
        key = f"{c['source']}:{c['id']}"
        if key in seen:
            continue
        seen.add(key)
        picked.append(c)
        if len(picked) >= max(1, min(limit, 10)):
            break

    unique: list[dict] = []
    for c in picked:
        if c["source"] == "fleet":
            unique.append(c)
            continue
        version = c["version"]
        tid = c["id"]
        row = c.pop("_row", {})
        detail = trader_detail(version, tid) or row
        ps = detail.get("portfolioSummary") or {}
        unique.append({
            "source": "arena",
            "id": str(tid),
            "name": f"Arena {version.upper()} #{tid}",
            "family": detail.get("family") or row.get("family"),
            "version": version,
            "scorePct": c["scorePct"],
            "returnPct": c["scorePct"],
            "equityUsd": detail.get("equityUsd"),
            "nDays": detail.get("nDays"),
            "bio": _arena_bio(version, detail),
            "portfolio": _portfolio_line_arena(ps),
            "performance": {
                "returnPct": c["scorePct"],
                "equityUsd": detail.get("equityUsd"),
                "nDays": detail.get("nDays"),
                "label": f"Arena {version.upper()} sim",
            },
            "href": f"#/arena/{version}/trader/{tid}",
            "badge": f"Arena {version.upper()}",
        })

    for i, t in enumerate(unique, 1):
        t["rank"] = i

    return {
        "ok": True,
        "generatedAt": summ.get("generatedAt") or reg.get("updatedAt"),
        "nCandidates": len(candidates),
        "traders": unique,
    }
