"""Local LLM runtime — NPU genai, Gemini (BYO key), or structured template fallback."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODEL_DIR = REPO / "models" / "reasoning"
STATUS_PATH = REPO / "data" / "reasoning" / "llm_status.json"
_DEFAULT_PMP_ENV = Path(r"C:\Users\nicho\prediction-market-predictor\.env")


def _write_status(doc: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def genai_available() -> bool:
    try:
        import onnxruntime_genai as og  # noqa: F401
        return True
    except ImportError:
        return False


def model_path() -> Path | None:
    env = os.getenv("NOSTRADAMUS_LLM_PATH", "").strip()
    if env:
        p = Path(env)
        return p if p.exists() else None
    for name in ("phi-3-mini-4k-instruct-directml", "phi-3-mini-4k-instruct-qnn", "phi-3-mini"):
        p = MODEL_DIR / name
        if p.exists():
            return p
    return None


def _google_api_key() -> str | None:
    for key in (os.getenv("GOOGLE_API_KEY"), os.getenv("NOSTRADAMUS_GOOGLE_API_KEY")):
        if key and key.strip():
            return key.strip()
    env_path = Path(os.getenv("NOSTRADAMUS_ENV_FILE", _DEFAULT_PMP_ENV))
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GOOGLE_API_KEY="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    return None


def _gemini_complete(message: str, context: dict, history: list[dict], max_tokens: int) -> str | None:
    key = _google_api_key()
    if not key:
        return None
    model = os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")
    import httpx

    system = (
        "You are Nostradamus, a concise ML trading analyst for a local paper-trading system. "
        "Answer the user's question using ONLY the JSON context provided. "
        "Be specific with numbers. Never claim live trading. Not financial advice. "
        "If data is missing, say what to run (e.g. learning_harness, reasoning_agent --tick)."
    )
    parts = [{"text": f"Context JSON:\n{json.dumps(context, indent=0)[:6000]}"}]
    for h in history[-6:]:
        role = "user" if h.get("role") == "user" else "model"
        parts.append({"text": f"{role}: {str(h.get('content', ''))[:500]}"})
    parts.append({"text": f"user: {message}"})

    body = {"contents": [{"role": "user", "parts": parts}],
            "systemInstruction": {"parts": [{"text": system}]}}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
           f":generateContent?key={key}")
    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        out_parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])
        text = "".join(p.get("text", "") for p in out_parts).strip()
        if text:
            _write_status({
                "backend": "gemini",
                "model": model,
                "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            return text
    except Exception as exc:
        _write_status({"backend": "gemini_error", "error": str(exc)[:300]})
    return None


def generate_text(prompt: str, max_tokens: int = 600) -> str | None:
    """Single-prompt LLM call for captain narratives and agent prompts."""
    text, backend = complete(prompt, max_tokens=max_tokens)
    if not text or backend == "template":
        return None
    return text.strip()


def complete(
    prompt: str,
    max_tokens: int = 512,
    *,
    message: str | None = None,
    context: dict | None = None,
    history: list | None = None,
) -> tuple[str, str]:
    """Return (text, backend). backend: genai | gemini | template."""
    ctx = context or {}
    user_msg = (message or "").strip()
    if not user_msg:
        for ln in reversed(prompt.splitlines()):
            if ln.lower().startswith("user:"):
                user_msg = ln.split(":", 1)[-1].strip()
                break
    hist = history or []

    gemini = _gemini_complete(user_msg, ctx, hist, max_tokens)
    if gemini:
        return gemini, "gemini"

    mp = model_path()
    if mp and genai_available():
        try:
            import onnxruntime_genai as og

            model = og.Model(str(mp))
            tokenizer = og.Tokenizer(model)
            params = og.GeneratorParams(model)
            params.set_search_options(max_length=max_tokens, temperature=0.35, top_p=0.9)
            params.input_ids = tokenizer.encode(prompt)
            gen = og.Generator(model, params)
            while not gen.is_done():
                gen.generate_next_token()
            out = tokenizer.decode(gen.get_sequence(0))
            _write_status({
                "backend": "onnxruntime_genai",
                "model": str(mp),
                "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            return out.strip(), "genai"
        except Exception as exc:
            _write_status({"backend": "genai_error", "error": str(exc)})

    from npu_runtime import primary_provider

    _write_status({
        "backend": "template",
        "npuProvider": primary_provider(),
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hint": "Set GOOGLE_API_KEY for richer chat, or install onnxruntime-genai + Phi-3.",
    })
    return _template_answer(user_msg, ctx), "template"


def _num(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _template_answer(message: str, ctx: dict) -> str:
    """Answer from structured context — never the same boilerplate for every question."""
    msg = (message or "").lower()
    pred = ctx.get("predictor") or {}
    inv = ctx.get("investor") or {}
    pipe = ctx.get("pipeline") or {}
    strat = ctx.get("strategy") or {}
    paper = ctx.get("paper") or {}
    pt = pred.get("test") or {}
    ret = _num(inv.get("totalReturnPct"))
    sharpe = _num(inv.get("sharpe"))
    dd = _num(inv.get("maxDrawdownPct"))
    acc = _num(pt.get("accuracy"))
    auc = _num(pt.get("auc"))
    health = ctx.get("healthScore")
    watch = strat.get("watchlist") or []
    narrative = (strat.get("narrative") or "")[:400]

    def _fmt_pct(x: float | None) -> str:
        return f"{x:.2f}%" if x is not None else "unknown"

    # --- intent routing ---
    if any(w in msg for w in ("negative", "why", "return", "losing", "loss", "red")):
        lines = [
            f"Investor **backtest** total return is {_fmt_pct(ret)} (Sharpe {sharpe if sharpe is not None else 'n/a'}, "
            f"max drawdown {_fmt_pct(dd)}).",
            "That number is from historical simulation with friction (costs, slippage, position caps) — not live PnL.",
        ]
        if ret is not None and ret < 0:
            lines.append(
                "Common drivers of a negative backtest here: (1) strict entry filters (min-proba / min-pred-ret) "
                "leaving capital idle or in weak names, (2) transaction costs on high-turnover policy, "
                "(3) regime mismatch — model trained on one volatility regime tested on another, "
                "(4) rank IC ≠ dollars — directional accuracy can look OK while dollar PnL is flat/negative."
            )
        if paper.get("equity"):
            lines.append(
                f"Forward **paper** book (reasoning agent): equity ${paper.get('equity'):,.0f}, "
                f"return {_fmt_pct(_num(paper.get('totalReturnPct')))} — trust this over backtest for 'are we learning'."
            )
        else:
            lines.append("No reasoning paper portfolio yet — run `python scripts/reasoning_agent.py --tick`.")
        if narrative:
            lines.append(f"Agent narrative: {narrative}")
        return "\n\n".join(lines)

    if any(w in msg for w in ("accura", "predictor", "auc", "f1", "model")):
        lines = [
            f"Predictor v3 **test** accuracy: {_fmt_pct(acc * 100 if acc and acc <= 1 else acc)}, "
            f"AUC {auc if auc is not None else 'n/a'}, n={pt.get('n', 'n/a')}.",
            "Accuracy on stocks is a weak profit proxy — rank IC and forward paper Sharpe matter more.",
        ]
        champ = pred.get("champion") or {}
        if champ.get("accuracy"):
            lines.append(f"Champion checkpoint accuracy: {champ.get('accuracy')}.")
        return "\n\n".join(lines)

    if any(w in msg for w in ("watchlist", "watch", "pick", "holding")):
        if watch:
            return f"Reasoning watchlist ({len(watch)} names): {', '.join(watch[:12])}." + (
                f"\n\nStrategy: {strat.get('name', 'balanced_momentum_overlay')}." if strat.get("name") else ""
            )
        return (
            "Watchlist is empty — reasoning agent hasn't ticked recently. "
            "Run `python scripts/reasoning_agent.py --tick` or wait for the intraday harness."
        )

    if any(w in msg for w in ("daytrade", "day trade", "fast", "intraday")):
        dt = pipe.get("daytrade") or {}
        ok = dt.get("manifestOk")
        mod = dt.get("modifiedAt", "missing")
        return (
            f"Daytrade manifest: {'ready' if ok else 'missing/stale'} (last update {mod}). "
            "Signals come from `generate_daytrade_signals.py`, gated by the same risk caps as swing. "
            "Paper only until manifests and forward metrics pass promotion gates."
        )

    if any(w in msg for w in ("health", "pipeline", "status", "harness", "npu")):
        checks = ctx.get("healthChecks") or []
        bad = [c["label"] for c in checks if not c.get("ok")]
        lines = [f"Pipeline health score: {health}/100."]
        if bad:
            lines.append("Needs attention: " + ", ".join(bad) + ".")
        else:
            lines.append("All core checks green.")
        h = pipe.get("harness") or {}
        if h.get("phase"):
            lines.append(f"Learning harness phase: {h.get('phase')} (mode {h.get('mode', 'n/a')}).")
        npu = pipe.get("npu") or {}
        if npu.get("primary"):
            lines.append(f"NPU runtime: {npu.get('primary')}.")
        return "\n\n".join(lines)

    if any(w in msg for w in ("strategy", "explain", "how")):
        name = strat.get("name") or strat.get("strategyId") or "balanced_momentum_overlay"
        lines = [
            f"Active strategy: **{name}** (paper simulation only).",
            "Stack: Predictor v3 edge → investor policy → congressional/insider overlays → "
            "session-aware risk caps from the continuous brain scheduler.",
        ]
        if narrative:
            lines.append(narrative)
        if ret is not None:
            lines.append(f"Investor backtest return: {_fmt_pct(ret)}; Sharpe {sharpe}.")
        return "\n\n".join(lines)

    # default summary
    return (
        f"Quick snapshot — Predictor test acc {_fmt_pct(_num(pt.get('accuracy')) * 100 if pt.get('accuracy') and pt.get('accuracy') <= 1 else _num(pt.get('accuracy')))}, "
        f"Investor backtest {_fmt_pct(ret)}, health {health}/100, "
        f"watchlist {len(watch)} names. "
        "Ask about negative returns, accuracy, watchlist, daytrade, or pipeline health."
    )


def _template_complete(prompt: str) -> str:
    """Legacy: parse flat prompt lines (no structured context)."""
    ctx: dict = {}
    for ln in prompt.splitlines():
        m = re.search(r"Predictor test accuracy:\s*([^,]+),\s*AUC:\s*(\S+)", ln)
        if m:
            ctx.setdefault("predictor", {}).setdefault("test", {})["accuracy"] = m.group(1)
            ctx["predictor"]["test"]["auc"] = m.group(2).rstrip(".")
        m = re.search(r"Investor backtest return %:\s*([^,]+),\s*Sharpe:\s*(\S+)", ln)
        if m:
            ctx.setdefault("investor", {})["totalReturnPct"] = m.group(1)
            ctx["investor"]["sharpe"] = m.group(2).rstrip(".")
        m = re.search(r"Pipeline health score:\s*(\d+)", ln)
        if m:
            ctx["healthScore"] = int(m.group(1))
        if ln.lower().startswith("user:"):
            return _template_answer(ln.split(":", 1)[-1].strip(), ctx)
    return _template_answer("", ctx)


if __name__ == "__main__":
    import sys

    p = sys.argv[1] if len(sys.argv) > 1 else "Why is the investor return negative?"
    text, backend = complete(p, context={"investor": {"totalReturnPct": -12.5, "sharpe": -0.4}})
    print(json.dumps({"backend": backend, "text": text}, indent=2))
