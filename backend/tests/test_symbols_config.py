"""Trading symbol configuration."""

from app.config import Settings, reset_settings_for_tests


def test_default_symbols_exclude_banknifty():
    s = Settings()
    assert s.symbols == ["NIFTY", "SENSEX"]
    assert "BANKNIFTY" not in s.symbols


def test_symbols_from_comma_env():
    s = Settings(symbols_csv="NIFTY,SENSEX")
    assert s.symbols == ["NIFTY", "SENSEX"]


def test_symbols_from_symbols_env(monkeypatch):
    monkeypatch.setenv("SYMBOLS", "NIFTY,SENSEX")
    reset_settings_for_tests()
    s = Settings()
    assert s.symbols == ["NIFTY", "SENSEX"]
    reset_settings_for_tests()
