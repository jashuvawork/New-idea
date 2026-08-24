"""Cumulative Volume Delta accumulator + option-CVD confirmation."""

from types import SimpleNamespace
from unittest.mock import patch

from app.services.cvd_store import (
    clear,
    get_cvd,
    get_cvd_acceleration,
    record_cvd_tick,
)


def setup_function():
    clear()


def test_cvd_accumulates_buying_on_upticks():
    key = "NSE_FO|TEST1"
    record_cvd_tick(key, 100.0, 50)  # first tick primes state, no delta
    record_cvd_tick(key, 101.0, 40)  # uptick -> +40
    record_cvd_tick(key, 102.0, 30)  # uptick -> +30
    read = get_cvd(key)
    assert read is not None
    assert read.recent == 70.0
    assert read.direction == "BUYING"


def test_cvd_accumulates_selling_on_downticks():
    key = "NSE_FO|TEST2"
    record_cvd_tick(key, 100.0, 50)
    record_cvd_tick(key, 99.0, 40)   # downtick -> -40
    record_cvd_tick(key, 98.0, 20)   # downtick -> -20
    read = get_cvd(key)
    assert read.recent == -60.0
    assert read.direction == "SELLING"


def test_cvd_flat_tick_carries_last_sign():
    key = "NSE_FO|TEST3"
    record_cvd_tick(key, 100.0, 10)
    record_cvd_tick(key, 101.0, 10)  # uptick -> +10, sign=+1
    record_cvd_tick(key, 101.0, 10)  # flat -> carry +1 -> +10
    read = get_cvd(key)
    assert read.recent == 20.0


def test_cvd_cumulative_mode_uses_delta():
    key = "NSE_FO|TEST4"
    record_cvd_tick(key, 100.0, 1000, cumulative=True)  # prime
    record_cvd_tick(key, 101.0, 1040, cumulative=True)  # +40 traded, uptick -> +40
    record_cvd_tick(key, 102.0, 1070, cumulative=True)  # +30 traded, uptick -> +30
    read = get_cvd(key)
    assert read.recent == 70.0
    assert read.direction == "BUYING"


def test_get_cvd_none_when_unseen():
    assert get_cvd("NSE_FO|NOPE") is None


def test_cvd_acceleration_compares_consecutive_signed_volume_rates():
    key = "NSE_FO|ACCEL"
    record_cvd_tick(key, 100.0, 1)  # prime
    with patch(
        "app.services.cvd_store.time.monotonic",
        side_effect=[70.0, 75.0, 88.0, 92.0, 95.0],
    ):
        record_cvd_tick(key, 101.0, 5)
        record_cvd_tick(key, 102.0, 5)
        record_cvd_tick(key, 103.0, 30)
        record_cvd_tick(key, 104.0, 40)
        read = get_cvd_acceleration(key, slice_seconds=15.0)

    assert read is not None
    assert read.previous == 10.0
    assert read.current == 70.0
    assert read.acceleration == 4.0
    assert read.direction == "BUYING_ACCELERATING"
    assert read.previous_samples == 2
    assert read.current_samples == 2


def test_cvd_acceleration_rejects_sparse_ticks():
    key = "NSE_FO|SPARSE"
    record_cvd_tick(key, 100.0, 1)
    with patch(
        "app.services.cvd_store.time.monotonic",
        side_effect=[75.0, 92.0, 95.0],
    ):
        record_cvd_tick(key, 101.0, 5)
        record_cvd_tick(key, 102.0, 100)
        read = get_cvd_acceleration(key, slice_seconds=15.0)

    assert read is not None
    assert read.acceleration > 0
    assert read.direction == "STABLE"


def test_cvd_acceleration_identifies_accelerating_selling():
    key = "NSE_FO|SELL_ACCEL"
    record_cvd_tick(key, 100.0, 1)
    with patch(
        "app.services.cvd_store.time.monotonic",
        side_effect=[70.0, 75.0, 88.0, 92.0, 95.0],
    ):
        record_cvd_tick(key, 99.0, 5)
        record_cvd_tick(key, 98.0, 5)
        record_cvd_tick(key, 97.0, 30)
        record_cvd_tick(key, 96.0, 40)
        read = get_cvd_acceleration(key, slice_seconds=15.0)

    assert read is not None
    assert read.acceleration == -4.0
    assert read.direction == "SELLING_ACCELERATING"


def test_option_cvd_confirms_buying_via_heatmap():
    from app.engines.advanced_indicators import option_cvd_confirms_buying

    clear()
    ce_key = "NSE_FO|CE24000"
    record_cvd_tick(ce_key, 100.0, 50)
    record_cvd_tick(ce_key, 101.0, 60)  # buying
    snap = SimpleNamespace(
        heatmap=[SimpleNamespace(strike=24000.0, callInstrumentKey=ce_key, putInstrumentKey="NSE_FO|PE24000")]
    )
    assert option_cvd_confirms_buying(snap, 24000.0, "CALL") is True
    # PUT side on the same strike has no buying ticks -> not confirmed.
    assert option_cvd_confirms_buying(snap, 24000.0, "PUT") is False
    # Unknown strike -> no key -> False.
    assert option_cvd_confirms_buying(snap, 25000.0, "CALL") is False


def test_option_cvd_acceleration_confirms_buying_via_heatmap():
    from app.engines.advanced_indicators import (
        option_cvd_acceleration_confirms_buying,
    )

    key = "NSE_FO|ACCEL_CE"
    record_cvd_tick(key, 100.0, 1)
    with patch(
        "app.services.cvd_store.time.monotonic",
        side_effect=[70.0, 75.0, 88.0, 92.0, 95.0],
    ):
        record_cvd_tick(key, 101.0, 5)
        record_cvd_tick(key, 102.0, 5)
        record_cvd_tick(key, 103.0, 30)
        record_cvd_tick(key, 104.0, 40)
        snap = SimpleNamespace(
            heatmap=[
                SimpleNamespace(
                    strike=24000.0,
                    callInstrumentKey=key,
                    putInstrumentKey="NSE_FO|ACCEL_PE",
                )
            ]
        )
        assert option_cvd_acceleration_confirms_buying(
            snap, 24000.0, "CALL",
        ) is True
        assert option_cvd_acceleration_confirms_buying(
            snap, 24000.0, "PUT",
        ) is False
