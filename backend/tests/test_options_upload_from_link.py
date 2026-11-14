"""Options upload link pipeline (local CSV, no network)."""

from pathlib import Path

from app.engines.options_csv_analysis import analyze_csv_file, build_training_profile
from app.engines.options_upload_from_link import training_store_dir


def test_analyze_csv_has_training(tmp_path: Path):
    csv_src = Path("/opt/cursor/artifacts/options_1m_upload/options_1m_2026-11_to_2026-11.csv")
    if not csv_src.is_file():
        return
    dest = tmp_path / "copy.csv"
    dest.write_bytes(csv_src.read_bytes())
    report = analyze_csv_file(dest, tmp_path / "out", include_all_series=False)
    assert report["macro"]["seriesCount"] > 0
    tr = report["training"]
    assert tr["trainedSeries"] == report["macro"]["seriesCount"]
    assert "NIFTY:CE" in tr["byIndexSide"] or "SENSEX:PE" in tr["byIndexSide"]


def test_build_training_profile_empty():
    assert build_training_profile([])["trainedSeries"] == 0


def test_training_store_dir_under_trade_store(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADE_STORE_DIR", str(tmp_path))
    from app.config import _cached_get_settings

    _cached_get_settings.cache_clear()
    assert training_store_dir() == tmp_path / "options_training"
    _cached_get_settings.cache_clear()