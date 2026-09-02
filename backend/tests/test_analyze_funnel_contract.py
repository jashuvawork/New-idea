"""CLI funnel contract analysis."""

from __future__ import annotations

import json
from pathlib import Path

from tests.fixtures.radar_archives import aug25_funnel_path
from scripts.analyze_funnel_contract import analyze_contract


def test_analyze_aug25_sensex_77800_pe_miss():
    funnel = aug25_funnel_path()
    rows = [json.loads(line) for line in funnel.read_text().splitlines() if line.strip()]
    report = analyze_contract(
        rows,
        symbol="SENSEX",
        side="PUT",
        strike=77800.0,
    )
    assert report["verdict"] in {"MISSED_AT_GATE", "MISSED_AFTER_DETECTION"}
    assert report["counts"]["detected"] > 10
    assert report["counts"]["entered"] == 0
    assert "chart_not_aligned" in str(report["gateBlockers"]["messageCounts"])
