"""Tradeable underlyings — NSE/BSE equity indices and MCX commodity options."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class UnderlyingKind(str, Enum):
    EQUITY_INDEX = "equity_index"
    COMMODITY = "commodity"


@dataclass(frozen=True)
class UnderlyingSpec:
    symbol: str
    instrument_key: str
    option_segment: str
    strike_step: float
    strike_bounds: tuple[float, float]
    fallback_lot_size: int
    premium_scale: float
    kind: UnderlyingKind
    weekly_expiry: bool
    # MCX mini futures symbol in Upstox master (rolling chain key via nearest FUT).
    futures_asset_symbol: Optional[str] = None
    # Upstox trading_symbol prefix → maps to `symbol` in parsers (e.g. GOLDM → GOLD).
    broker_aliases: tuple[str, ...] = ()


# Upstox option-chain /option/contract keys (underlying refs, not rolling fut legs).
_REGISTRY: dict[str, UnderlyingSpec] = {
    "NIFTY": UnderlyingSpec(
        symbol="NIFTY",
        instrument_key="NSE_INDEX|Nifty 50",
        option_segment="NSE_FO",
        strike_step=50.0,
        strike_bounds=(15_000.0, 35_000.0),
        fallback_lot_size=65,
        premium_scale=1.0,
        kind=UnderlyingKind.EQUITY_INDEX,
        weekly_expiry=True,
    ),
    "BANKNIFTY": UnderlyingSpec(
        symbol="BANKNIFTY",
        instrument_key="NSE_INDEX|Nifty Bank",
        option_segment="NSE_FO",
        strike_step=100.0,
        strike_bounds=(30_000.0, 70_000.0),
        fallback_lot_size=30,
        premium_scale=3.0,
        kind=UnderlyingKind.EQUITY_INDEX,
        weekly_expiry=True,
    ),
    "SENSEX": UnderlyingSpec(
        symbol="SENSEX",
        instrument_key="BSE_INDEX|SENSEX",
        option_segment="BSE_FO",
        strike_step=100.0,
        strike_bounds=(60_000.0, 90_000.0),
        fallback_lot_size=20,
        premium_scale=3.0,
        kind=UnderlyingKind.EQUITY_INDEX,
        weekly_expiry=True,
    ),
    "CRUDEOIL": UnderlyingSpec(
        symbol="CRUDEOIL",
        instrument_key="MCX_FO|573423",
        option_segment="MCX_FO",
        strike_step=50.0,
        strike_bounds=(3_000.0, 15_000.0),
        fallback_lot_size=10,
        premium_scale=0.45,
        kind=UnderlyingKind.COMMODITY,
        weekly_expiry=False,
        futures_asset_symbol="CRUDEOILM",
    ),
    "NATURALGAS": UnderlyingSpec(
        symbol="NATURALGAS",
        instrument_key="MCX_FO|574320",
        option_segment="MCX_FO",
        strike_step=5.0,
        strike_bounds=(50.0, 1_200.0),
        fallback_lot_size=250,
        premium_scale=0.35,
        kind=UnderlyingKind.COMMODITY,
        weekly_expiry=False,
        futures_asset_symbol="NATGASMINI",
    ),
    "GOLD": UnderlyingSpec(
        symbol="GOLD",
        instrument_key="MCX_FO|575011",
        option_segment="MCX_FO",
        strike_step=500.0,
        strike_bounds=(100_000.0, 200_000.0),
        fallback_lot_size=100,
        premium_scale=0.55,
        kind=UnderlyingKind.COMMODITY,
        weekly_expiry=False,
        futures_asset_symbol="GOLDM",
        broker_aliases=("GOLDM",),
    ),
    "SILVER": UnderlyingSpec(
        symbol="SILVER",
        instrument_key="MCX_FO|483080",
        option_segment="MCX_FO",
        strike_step=1000.0,
        strike_bounds=(130_000.0, 420_000.0),
        fallback_lot_size=5,
        premium_scale=0.35,
        kind=UnderlyingKind.COMMODITY,
        weekly_expiry=False,
        futures_asset_symbol="SILVERM",
        broker_aliases=("SILVERM",),
    ),
}

COMMODITY_SYMBOLS: frozenset[str] = frozenset(
    s.symbol for s in _REGISTRY.values() if s.kind == UnderlyingKind.COMMODITY
)


def all_specs() -> dict[str, UnderlyingSpec]:
    return dict(_REGISTRY)


def get_spec(symbol: str) -> Optional[UnderlyingSpec]:
    return _REGISTRY.get(str(symbol or "").strip().upper())


def known_symbol(symbol: str) -> bool:
    return get_spec(symbol) is not None


def is_commodity(symbol: str) -> bool:
    spec = get_spec(symbol)
    return spec is not None and spec.kind == UnderlyingKind.COMMODITY


def index_keys_map() -> dict[str, str]:
    return {k: v.instrument_key for k, v in _REGISTRY.items()}


def option_segments_map() -> dict[str, str]:
    return {k: v.option_segment for k, v in _REGISTRY.items()}


def strike_step(symbol: str) -> float:
    spec = get_spec(symbol)
    if spec:
        return spec.strike_step
    return 50.0


def strike_bounds(symbol: str) -> Optional[tuple[float, float]]:
    spec = get_spec(symbol)
    return spec.strike_bounds if spec else None


def fallback_lot_size(symbol: str) -> int:
    spec = get_spec(symbol)
    if spec:
        return spec.fallback_lot_size
    return 65


def premium_scale(symbol: str) -> float:
    spec = get_spec(symbol)
    if spec:
        return max(0.05, float(spec.premium_scale))
    return 1.0


def broker_symbol_pattern() -> str:
    """Alternation of registered symbols for regex (longest first)."""
    tokens: list[str] = []
    for sym, spec in _REGISTRY.items():
        tokens.append(sym)
        tokens.extend(spec.broker_aliases)
    names = sorted(set(tokens), key=len, reverse=True)
    return "|".join(names)


def canonical_symbol(broker_token: str) -> str:
    """Map Upstox option root (e.g. GOLDM) to configured symbol (GOLD)."""
    token = str(broker_token or "").strip().upper()
    if token in _REGISTRY:
        return token
    for sym, spec in _REGISTRY.items():
        if token in {a.upper() for a in spec.broker_aliases}:
            return sym
    return token