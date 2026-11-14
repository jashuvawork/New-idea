"""Download options CSV/ZIP from URL and run analysis + training profile."""

from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.options_csv_analysis import analyze_csv_file

IST = ZoneInfo("Asia/Kolkata")
MAX_BYTES = 120 * 1024 * 1024
ALLOWED_HOST_SUFFIXES = (
    "drive.google.com",
    "docs.google.com",
    "googleusercontent.com",
    "githubusercontent.com",
    "amazonaws.com",
    "jashuvatrade.xyz",
    "cloudfront.net",
)


def _extract_drive_id(url: str) -> str | None:
    m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None


def _resolve_download_url(url: str) -> str:
    did = _extract_drive_id(url)
    if did:
        return f"https://drive.google.com/uc?export=download&id={did}"
    return url.strip()


def _host_allowed(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    host = host.lower()
    if host in ("localhost", "127.0.0.1"):
        return True
    return any(host == suf or host.endswith("." + suf) for suf in ALLOWED_HOST_SUFFIXES)


def download_url(url: str, dest: Path, *, timeout: float = 300.0) -> int:
    resolved = _resolve_download_url(url)
    if not _host_allowed(resolved):
        raise ValueError(f"host not allowed: {urllib.parse.urlparse(resolved).hostname}")
    req = urllib.request.Request(resolved, headers={"User-Agent": "NexusQuant-options-upload/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        chunk = resp.read(MAX_BYTES + 1)
        if len(chunk) > MAX_BYTES:
            raise ValueError(f"download exceeds {MAX_BYTES} bytes")
        dest.write_bytes(chunk)
    return dest.stat().st_size


def _find_csv(work_dir: Path) -> Path:
    csvs = list(work_dir.rglob("*.csv"))
    if not csvs:
        raise ValueError("no CSV found in download (expected options_1m *.csv)")
    preferred = [p for p in csvs if "options" in p.name.lower() and "1m" in p.name.lower()]
    return preferred[0] if preferred else max(csvs, key=lambda p: p.stat().st_size)


def _unpack_if_zip(path: Path, work_dir: Path) -> Path:
    if path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            zf.extractall(work_dir)
        return _find_csv(work_dir)
    if path.suffix.lower() == ".csv":
        return path
    raise ValueError("unsupported file type (use .zip or .csv)")


def training_store_dir() -> Path:
    settings = get_settings()
    return Path(settings.trade_store_dir) / "options_training"


def run_options_upload_from_link(
    url: str,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    job_id = uuid4().hex[:12]
    work = Path(tempfile.mkdtemp(prefix="nexus_options_upload_"))
    try:
        raw = work / "download.bin"
        nbytes = download_url(url, raw)
        csv_path = _unpack_if_zip(raw, work)
        out_dir = work / "out"
        report = analyze_csv_file(csv_path, out_dir, include_all_series=False)
        result: dict[str, Any] = {
            "status": "completed",
            "jobId": job_id,
            "sourceUrl": url,
            "downloadBytes": nbytes,
            "csvFile": csv_path.name,
            "generatedAt": datetime.now(IST).isoformat(),
            "analysis": {
                "macro": report["macro"],
                "baseRipLikeSamples": report.get("baseRipLikeSamples", [])[:20],
                "dailyTopMfe": report.get("dailyTopMfe", []),
            },
            "trainingResults": report["training"],
        }
        if persist:
            store = training_store_dir()
            store.mkdir(parents=True, exist_ok=True)
            job_path = store / "jobs" / f"{job_id}.json"
            job_path.parent.mkdir(parents=True, exist_ok=True)
            job_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
            latest = store / "latest.json"
            latest.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
            result["stored"] = {"job": str(job_path), "latest": str(latest)}
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def load_latest_training() -> dict[str, Any] | None:
    latest = training_store_dir() / "latest.json"
    if not latest.is_file():
        return None
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None