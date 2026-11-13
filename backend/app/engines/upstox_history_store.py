"""On-disk Upstox candle chunks for resumable multi-year pulls (EC2 / TRADE_STORE_DIR)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def history_root(base_dir: Path, symbol: str) -> Path:
    return base_dir / "upstox_history" / symbol.upper()


def chunk_filename(lo: date, hi: date) -> str:
    return f"{lo.isoformat()}_{hi.isoformat()}.jsonl"


def chunk_path(root: Path, lo: date, hi: date) -> Path:
    return root / "minutes_1m" / "chunks" / chunk_filename(lo, hi)


def manifest_path(root: Path) -> Path:
    return root / "manifest.json"


def job_status_path(root: Path) -> Path:
    return root / "job_status.json"


def _candle_to_json(c: dict[str, Any]) -> dict[str, Any]:
    ts = c["ts"]
    if isinstance(ts, datetime):
        ts = ts.astimezone(IST).isoformat()
    return {
        "ts": ts,
        "open": c["open"],
        "high": c["high"],
        "low": c["low"],
        "close": c["close"],
        "volume": c.get("volume", 0.0),
        "oi": c.get("oi", 0.0),
    }


def write_chunk(path: Path, candles: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for c in candles:
            fh.write(json.dumps(_candle_to_json(c), ensure_ascii=False))
            fh.write("\n")
    return path.stat().st_size


def read_chunk(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            ts = datetime.fromisoformat(str(obj["ts"]))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            rows.append({**obj, "ts": ts.astimezone(IST)})
    return rows


def iter_chunk_files(root: Path) -> Iterator[Path]:
    chunks_dir = root / "minutes_1m" / "chunks"
    if not chunks_dir.is_dir():
        return
    for p in sorted(chunks_dir.glob("*.jsonl")):
        yield p


def load_all_minute_candles(root: Path) -> list[dict[str, Any]]:
    by_ts: dict[datetime, dict[str, Any]] = {}
    for path in iter_chunk_files(root):
        for c in read_chunk(path):
            by_ts[c["ts"]] = c
    return [by_ts[k] for k in sorted(by_ts)]


def load_manifest(root: Path) -> dict[str, Any]:
    path = manifest_path(root)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_manifest(root: Path, data: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    manifest_path(root).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def write_job_status(root: Path, data: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    data["updatedAt"] = datetime.now(IST).isoformat()
    job_status_path(root).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def read_job_status(root: Path) -> dict[str, Any]:
    path = job_status_path(root)
    if not path.is_file():
        return {"status": "idle"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "unknown"}


def chunk_completed(root: Path, lo: date, hi: date) -> bool:
    p = chunk_path(root, lo, hi)
    return p.is_file() and p.stat().st_size > 0
