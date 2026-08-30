"""Operator event log regressions."""

from pathlib import Path

from app.services.operator_event_log import append_operator_event


def test_append_operator_event_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_STORE_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    append_operator_event("entry_blocked", {"symbol": "NIFTY", "reason": "chart_alignment"})
    files = list(Path(tmp_path).glob("operator_events/*.jsonl"))
    assert len(files) == 1
    payload = files[0].read_text(encoding="utf-8")
    assert "entry_blocked" in payload
    assert "chart_alignment" in payload

    get_settings.cache_clear()
