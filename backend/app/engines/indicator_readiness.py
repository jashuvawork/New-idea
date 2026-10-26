"""Minimum bar counts for indicator warmup — avoid fake zeros at the open."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# MACD 12/26/9 needs slow + signal (26+9)
MACD_MIN_CLOSES = 35
RSI_MIN_CLOSES = 15
EMA21_MIN_CLOSES = 21
ADX_MIN_CLOSES = 28
SUPERTREND_MIN_CLOSES = 11
SQUEEZE_MIN_CLOSES = 21
ICHIMOKU_SENKOU_B_MIN = 52
# Displaced cloud (26 back) on 5m ≈ 52 + 26 bars of history
ICHIMOKU_CLOUD_MIN_5M = 78


@dataclass(frozen=True)
class IndicatorReadiness:
    indicator_bar_count: int = 0
    rsi_ready: bool = False
    macd_ready: bool = False
    ema21_ready: bool = False
    ichimoku_ready: bool = False
    ichimoku_cloud_ready: bool = False
    adx_ready: bool = False
    squeeze_ready: bool = False
    indicators_warm: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "indicatorBarCount": self.indicator_bar_count,
            "rsiReady": self.rsi_ready,
            "macdReady": self.macd_ready,
            "ema21Ready": self.ema21_ready,
            "ichimokuReady": self.ichimoku_ready,
            "ichimokuCloudReady": self.ichimoku_cloud_ready,
            "adxReady": self.adx_ready,
            "squeezeReady": self.squeeze_ready,
            "indicatorsWarm": self.indicators_warm,
        }


def readiness_from_closes(
    closes: list[float],
    *,
    ichimoku_cloud_min: int = ICHIMOKU_CLOUD_MIN_5M,
) -> IndicatorReadiness:
    n = len(closes) if closes else 0
    rsi_ready = n >= RSI_MIN_CLOSES + 1
    macd_ready = n >= MACD_MIN_CLOSES
    ema21_ready = n >= EMA21_MIN_CLOSES
    ich_ready = n >= ICHIMOKU_SENKOU_B_MIN
    cloud_ready = n >= ichimoku_cloud_min
    adx_ready = n >= ADX_MIN_CLOSES * 2
    squeeze_ready = n >= SQUEEZE_MIN_CLOSES
    warm = macd_ready and ema21_ready and rsi_ready
    return IndicatorReadiness(
        indicator_bar_count=n,
        rsi_ready=rsi_ready,
        macd_ready=macd_ready,
        ema21_ready=ema21_ready,
        ichimoku_ready=ich_ready,
        ichimoku_cloud_ready=cloud_ready,
        adx_ready=adx_ready,
        squeeze_ready=squeeze_ready,
        indicators_warm=warm,
    )
