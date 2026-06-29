"""Trading symbol configuration."""

from app.config import Settings, get_settings


def test_default_symbols_exclude_banknifty():
    s = Settings()
    assert s.symbols == ["NIFTY", "SENSEX"]
    assert "BANKNIFTY" not in s.symbols


def test_symbols_from_comma_env():
    s = Settings(symbols_csv="NIFTY,SENSEX")
    assert s.symbols == ["NIFTY", "SENSEX"]


def test_symbols_from_symbols_env(monkeypatch):
    monkeypatch.setenv("SYMBOLS", "NIFTY,SENSEX")
    get_settings.cache_clear()
    s = Settings()
    assert s.symbols == ["NIFTY", "SENSEX"]
    get_settings.cache_clear()
