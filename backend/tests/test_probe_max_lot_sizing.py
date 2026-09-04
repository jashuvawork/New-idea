"""Probe 40% cap vs max-lot eligibility."""

from unittest.mock import MagicMock, patch

from app.engines.entry_timing import apply_probe_or_max_lot_sizing, timing_allows_full_size


def test_hot_timing_keeps_lots_for_max_path():
    timing = {"assessment": "GOOD", "action": "allow"}
    lots, meta = apply_probe_or_max_lot_sizing(
        18, symbol="NIFTY", premium=146.95, timing=timing,
    )
    assert lots == 18
    assert meta["sizingMode"] == "max_lots_eligible"
    assert timing_allows_full_size(timing)


@patch("app.engines.entry_day_adaptive.get_settings")
@patch("app.engines.day_adaptive_engine.classify_day_type", return_value="CHOP")
def test_cold_base_uses_40pct_cap_not_max_lots(mock_classify, mock_settings):
    s = MagicMock()
    s.entry_day_adaptive_enabled = True
    s.probe_entry_max_capital_pct = 0.40
    s.entry_day_chop_probe_max_capital_pct = 0.40
    s.entry_day_chop_cold_base_lot_cap = 99
    s.entry_day_chop_coil_top_max_position_frac = 0.40
    s.entry_day_chop_coil_top_min_run_pct = 0.06
    s.entry_day_chop_coil_top_max_run_pct = 0.25
    s.entry_day_chop_building_cold_min_velocity_3s = 1.5
    s.entry_day_chop_block_building_watch_cold_base = True
    s.entry_day_chop_rally_coil_top_max_position_frac = 0.40
    s.entry_day_chop_rally_building_cold_min_velocity_3s = 1.5
    mock_settings.return_value = s

    timing = {
        "assessment": "COLD_BASE",
        "action": "lot_cap",
        "lotCap": None,
    }
    with patch(
        "app.engines.capital_allocator.max_lots_for_capital_pct",
        return_value=7,
    ):
        lots, meta = apply_probe_or_max_lot_sizing(
            18,
            symbol="NIFTY",
            premium=146.95,
            timing=timing,
            settings=s,
        )
    assert lots == 7
    assert meta["sizingMode"] == "probe_capital_pct"
    assert meta["probeMaxCapitalPct"] == 0.40
