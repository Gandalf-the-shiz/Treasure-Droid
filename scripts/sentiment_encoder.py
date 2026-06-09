"""Headline sentiment encoder — ONNX Runtime with NPU/QNN auto-detection.

Loads a pre-converted ONNX FinBERT (3-class classifier: negative / neutral /
positive) from the HuggingFace Hub and scores news headlines. Returns a
`{neg, neu, pos}` distribution plus a signed scalar in [-1, 1] suitable as a
feature column for the investor model.

The runtime tries execution providers in this order:
    1. QNNExecutionProvider   (Snapdragon Hexagon NPU, ~45 TOPS)
    2. DmlExecutionProvider   (DirectML — GPU/NPU fallback on Windows)
    3. CPUExecutionProvider   (always available)

This module is intentionally dependency-light — it avoids `transformers`,
`tokenizers`, `safetensors`, and `optimum` because none of them ship win_arm64
wheels right now. WordPiece tokenization is implemented in pure Python.

Usage:
    python scripts/sentiment_encoder.py --demo
    Get-Content headlines.txt | python scripts/sentiment_encoder.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "sentiment"
ONNX_PATH = MODEL_DIR / "model.onnx"
VOCAB_PATH = MODEL_DIR / "vocab.txt"
CONFIG_PATH = MODEL_DIR / "config.json"

HF_REPO = "Xenova/finbert"
HF_FILES = {
    "model.onnx": f"https://huggingface.co/{HF_REPO}/resolve/main/onnx/model.onnx",
    "vocab.txt": f"https://huggingface.co/{HF_REPO}/resolve/main/vocab.txt",
    "config.json": f"https://huggingface.co/{HF_REPO}/resolve/main/config.json",
}

try:
    from npu_runtime import select_providers as _select_npu_providers
except ImportError:
    _select_npu_providers = None

PROVIDER_PRIORITY = (
    "QNNExecutionProvider",
    "DmlExecutionProvider",
    "CPUExecutionProvider",
)
DEFAULT_LABELS = ("positive", "negative", "neutral")

_PUNCT_RE = re.compile(
    r"[\u0000-\u002F\u003A-\u0040\u005B-\u0060\u007B-\u007E\u2000-\u206F\u2E00-\u2E7F]"
)


class WordPieceTokenizer:
    def __init__(self, vocab_path: Path, max_len: int = 96):
        self.vocab: dict[str, int] = {}
        for i, line in enumerate(vocab_path.read_text(encoding="utf-8").splitlines()):
            token = line.rstrip("\n")
            if token:
                self.vocab[token] = i
        self.cls = self.vocab["[CLS]"]
        self.sep = self.vocab["[SEP]"]
        self.pad = self.vocab["[PAD]"]
        self.unk = self.vocab["[UNK]"]
        self.max_len = max_len

    def _basic_tokenize(self, text: str) -> list[str]:
        text = unicodedata.normalize("NFD", text)
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
        text = text.lower()
        out: list[str] = []
        for chunk in text.split():
            buf = ""
            for ch in chunk:
                if _PUNCT_RE.match(ch):
                    if buf:
                        out.append(buf)
                        buf = ""
                    out.append(ch)
                else:
                    buf += ch
            if buf:
                out.append(buf)
        return out

    def _wordpiece(self, word: str) -> list[int]:
        if word in self.vocab:
            return [self.vocab[word]]
        tokens: list[int] = []
        start = 0
        while start < len(word):
            end = len(word)
            cur = None
            while start < end:
                piece = word[start:end] if start == 0 else "##" + word[start:end]
                if piece in self.vocab:
                    cur = self.vocab[piece]
                    break
                end -= 1
            if cur is None:
                return [self.unk]
            tokens.append(cur)
            start = end
        return tokens

    def encode_batch(self, texts: list[str]) -> tuple[list[list[int]], list[list[int]]]:
        all_ids: list[list[int]] = []
        for t in texts:
            ids = [self.cls]
            for w in self._basic_tokenize(t):
                ids.extend(self._wordpiece(w))
                if len(ids) >= self.max_len - 1:
                    ids = ids[: self.max_len - 1]
                    break
            ids.append(self.sep)
            all_ids.append(ids)
        max_len = max(len(x) for x in all_ids)
        input_ids: list[list[int]] = []
        attn: list[list[int]] = []
        for ids in all_ids:
            pad = max_len - len(ids)
            input_ids.append(ids + [self.pad] * pad)
            attn.append([1] * len(ids) + [0] * pad)
        return input_ids, attn


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[sentiment] downloading {url} -> {dest.relative_to(ROOT)}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Nostradamus/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        total = int(r.headers.get("content-length", 0))
        seen = 0
        chunk = 1 << 16
        while True:
            buf = r.read(chunk)
            if not buf:
                break
            f.write(buf)
            seen += len(buf)
            if total:
                pct = 100 * seen / total
                print(f"\r  {seen / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MiB ({pct:.0f}%)", end="", flush=True)
        print()


def ensure_model() -> None:
    for name, url in HF_FILES.items():
        dest = MODEL_DIR / name
        if not dest.exists() or dest.stat().st_size == 0:
            _download(url, dest)


def select_providers() -> list:
    """Legacy provider list for callers that still use providers= kwarg."""
    if _select_npu_providers is not None:
        return _select_npu_providers()
    return list(PROVIDER_PRIORITY)


@dataclass
class SentimentResult:
    headline: str
    label: str
    score: float
    proba: dict[str, float] = field(default_factory=dict)


class SentimentEncoder:
    def __init__(self, max_len: int = 96):
        self.max_len = max_len
        self._session = None
        self._tokenizer: WordPieceTokenizer | None = None
        self._providers: list[str] = []
        self._id2label: dict[int, str] = {}

    def _lazy_init(self) -> None:
        if self._session is not None:
            return
        ensure_model()
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        try:
            from npu_runtime import create_inference_session
            self._session = create_inference_session(ONNX_PATH, sess_options=opts)
        except Exception:
            import onnxruntime as ort
            providers = select_providers()
            avail = set(ort.get_available_providers())
            legacy = [p for p in providers if p in avail or (isinstance(p, tuple) and p[0] in avail)]
            if not legacy:
                legacy = ["CPUExecutionProvider"]
            self._session = ort.InferenceSession(str(ONNX_PATH), sess_options=opts, providers=legacy)
        self._providers = self._session.get_providers()
        self._tokenizer = WordPieceTokenizer(VOCAB_PATH, max_len=self.max_len)

        cfg = json.loads(CONFIG_PATH.read_text())
        id2label = cfg.get("id2label") or {str(i): l for i, l in enumerate(DEFAULT_LABELS)}
        self._id2label = {int(k): str(v).lower() for k, v in id2label.items()}
        print(f"[sentiment] ready - providers={self._providers}  labels={list(self._id2label.values())}", flush=True)

    @property
    def active_provider(self) -> str:
        self._lazy_init()
        return self._providers[0] if self._providers else "unknown"

    def score(self, headlines: Iterable[str]) -> list[SentimentResult]:
        import numpy as np

        self._lazy_init()
        assert self._session is not None and self._tokenizer is not None
        items = [h.strip() for h in headlines if h and h.strip()]
        if not items:
            return []

        input_ids, attn = self._tokenizer.encode_batch(items)
        ids_arr = np.asarray(input_ids, dtype=np.int64)
        mask_arr = np.asarray(attn, dtype=np.int64)
        tok_type = np.zeros_like(ids_arr)

        feeds: dict = {}
        wanted = {i.name for i in self._session.get_inputs()}
        if "input_ids" in wanted:
            feeds["input_ids"] = ids_arr
        if "attention_mask" in wanted:
            feeds["attention_mask"] = mask_arr
        if "token_type_ids" in wanted:
            feeds["token_type_ids"] = tok_type

        logits = self._session.run(None, feeds)[0]
        z = logits - logits.max(axis=1, keepdims=True)
        ez = np.exp(z)
        probs = ez / ez.sum(axis=1, keepdims=True)

        results: list[SentimentResult] = []
        for headline, row in zip(items, probs):
            proba = {self._id2label.get(i, str(i)): float(row[i]) for i in range(len(row))}
            pos = proba.get("positive", 0.0)
            neg = proba.get("negative", 0.0)
            score = float(pos - neg)
            label = max(proba, key=proba.get)
            results.append(SentimentResult(headline=headline, label=label, score=score, proba=proba))
        return results


def _print_json(results: list[SentimentResult], provider: str, elapsed_ms: float) -> None:
    payload = {
        "provider": provider,
        "elapsed_ms": round(elapsed_ms, 2),
        "items": [
            {
                "headline": r.headline,
                "label": r.label,
                "score": round(r.score, 4),
                "proba": {k: round(v, 4) for k, v in r.proba.items()},
            }
            for r in results
        ],
    }
    print(json.dumps(payload, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    if args.demo:
        headlines = [
            "Apple beats Q1 earnings, raises full-year guidance",
            "Tesla recalls 1.2M vehicles over autopilot safety probe",
            "Federal Reserve holds rates steady, signals patience",
            "Nvidia announces breakthrough AI chip, stock surges premarket",
            "Boeing CEO resigns amid mounting 737 MAX investigations",
            "Microsoft and OpenAI extend partnership, new Azure region launching",
        ]
    else:
        if sys.stdin.isatty():
            sys.exit("no input — pipe headlines on stdin or pass --demo")
        headlines = [line for line in sys.stdin.read().splitlines() if line.strip()]

    enc = SentimentEncoder()
    t0 = time.perf_counter()
    results = enc.score(headlines)
    elapsed = (time.perf_counter() - t0) * 1000
    _print_json(results, enc.active_provider, elapsed)


if __name__ == "__main__":
    main()
