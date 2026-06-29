"""Trading symbol configuration."""

from app.config import Settings


def test_default_symbols_exclude_banknifty():
    s = Settings()
    assert s.symbols == ["NIFTY", "SENSEX"]
    assert "BANKNIFTY" not in s.symbols


def test_symbols_from_comma_env():
    s = Settings(symbols="NIFTY,SENSEX")
    assert s.symbols == ["NIFTY", "SENSEX"]
