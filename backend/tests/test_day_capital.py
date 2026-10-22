"""Today's book is one number, posted or restored, above or below the env cap."""

import asyncio
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.engines.auto_trader import set_capital
from app.engines.capital_allocator import (
    _capital_base_for_stages,
    book_capital_inr,
    effective_daily_loss_stop_inr,
    refresh_capital_from_upstox,
    reset_capital_for_tests,
    restore_day_capital,
    set_manual_capital_limit,
)

ROOT = Path(__file__).resolve().parents[2]


def _settings(*, book: float = 200_000, live: bool = False):
    return SimpleNamespace(
        fallback_capital_inr=book,
        max_sizing_capital_inr=book,
        per_trade_capital_pct=0.90,
        lot_size_nifty=65,
        lot_size_banknifty=30,
        lot_size_sensex=20,
        use_upstox_lot_sizes=False,
        simple_min_lots=1,
        use_upstox_capital_for_sizing=live,
        enable_live_trading=live,
        symbols=["NIFTY", "SENSEX"],
        upstox_expiries_cache_seconds=3600,
    )


def test_day_book_can_rise_above_the_env_cap():
    reset_capital_for_tests()
    settings = _settings(book=200_000)
    with patch("app.engines.capital_allocator.get_settings", return_value=settings):
        snap = set_manual_capital_limit(275_000)
    assert snap.availableMarginInr == 275_000
    assert snap.perTradeCapitalInr == pytest.approx(247_500)
    assert snap.source == "manual"
    assert book_capital_inr() == 275_000
    assert _capital_base_for_stages() == 275_000


def test_day_book_can_fall_below_the_env_cap():
    reset_capital_for_tests()
    settings = _settings(book=275_000)
    with patch("app.engines.capital_allocator.get_settings", return_value=settings):
        snap = set_manual_capital_limit(150_000)
    assert snap.availableMarginInr == 150_000
    assert book_capital_inr() == 150_000


def test_daily_loss_stop_is_fifteen_percent_of_the_day_book():
    reset_capital_for_tests()
    settings = _settings(book=275_000)
    settings.daily_loss_stop_from_capital = True
    settings.daily_loss_stop_pct = 0.15
    settings.daily_loss_stop_inr = 20_000
    with patch("app.engines.capital_allocator.get_settings", return_value=settings):
        assert effective_daily_loss_stop_inr() == 41_250
        set_manual_capital_limit(100_000)
        assert effective_daily_loss_stop_inr() == 15_000


def test_day_book_rejects_a_typo_below_the_floor():
    reset_capital_for_tests()
    with pytest.raises(ValueError):
        set_manual_capital_limit(275)


def test_broker_margin_cannot_exceed_the_day_book():
    reset_capital_for_tests()
    settings = _settings(book=200_000, live=True)

    class Client:
        async def get_funds(self, force=False):
            return {"equity": {"available_margin": 500_000, "net": 500_000}}

    with patch("app.engines.capital_allocator.get_settings", return_value=settings):
        set_manual_capital_limit(275_000)
        snap = asyncio.run(refresh_capital_from_upstox(Client()))
    assert snap.availableMarginInr == 275_000


def test_day_book_is_restored_after_restart(tmp_path):
    reset_capital_for_tests()
    settings = _settings(book=200_000)
    path = tmp_path / "day_capital.json"
    with patch("app.engines.capital_allocator.get_settings", return_value=settings), patch(
        "app.engines.capital_allocator._day_capital_path", return_value=path
    ):
        set_capital(275_000)
        reset_capital_for_tests()
        snap = restore_day_capital()
    assert path.is_file()
    assert snap is not None
    assert snap.availableMarginInr == 275_000
    assert book_capital_inr() == 275_000


def test_set_day_capital_script_writes_the_env_and_rejects_a_small_number(tmp_path):
    env_file = tmp_path / "env"
    env_file.write_text("FALLBACK_CAPITAL_INR=200000\nMAX_SIZING_CAPITAL_INR=200000\n")
    script = ROOT / "deploy/set-day-capital.sh"
    bad = subprocess.run(
        ["bash", str(script), "275"],
        env={**os.environ, "ENV_FILE": str(env_file), "DAY_CAPITAL_SKIP_POST": "1"},
        capture_output=True,
        text=True,
    )
    assert bad.returncode != 0
    good = subprocess.run(
        ["bash", str(script), "275000"],
        env={**os.environ, "ENV_FILE": str(env_file), "DAY_CAPITAL_SKIP_POST": "1"},
        capture_output=True,
        text=True,
        check=True,
    )
    text = env_file.read_text()
    assert "FALLBACK_CAPITAL_INR=275000" in text
    assert "MAX_SIZING_CAPITAL_INR=275000" in text
    assert "275000" in good.stdout
