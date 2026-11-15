"""Tests for merge_years_index_chunk_profiles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.merge_years_index_chunk_profiles import merge_chunk_dir


def _chunk_file(tmp_path: Path, name: str, buckets: dict) -> None:
    payload = {
        "symbol": "NIFTY",
        "upstoxMinutes": {
            "candleCount": 100,
            "profile": {"buckets": buckets},
        },
    }
    (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")


def test_merge_chunk_dir_sums_buckets(tmp_path: Path) -> None:
    b1 = {
        "09:15": {
            "CALL": {"15": {"wins": 2, "samples": 10}},
            "PUT": {"15": {"wins": 3, "samples": 10}},
        }
    }
    b2 = {
        "09:15": {
            "CALL": {"15": {"wins": 1, "samples": 5}},
            "PUT": {"15": {"wins": 0, "samples": 5}},
        }
    }
    _chunk_file(tmp_path, "chunk_000_a.json", b1)
    _chunk_file(tmp_path, "chunk_001_b.json", b2)

    report = merge_chunk_dir(tmp_path, symbol="NIFTY")
    cell = report["profile"]["buckets"]["09:15"]["CALL"]["15"]
    assert cell["wins"] == 3
    assert cell["samples"] == 15
    assert cell["probabilityPct"] == 20.0
    assert report["chunkFiles"] == 2


def test_merge_chunk_dir_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        merge_chunk_dir(tmp_path)