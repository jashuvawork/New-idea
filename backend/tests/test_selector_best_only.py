"""Best-only selector — one top-ranked explosion per radar cycle."""

from unittest.mock import patch

from app.config import Settings


def test_selector_best_only_default_enabled():
    assert Settings().selector_best_only_enabled is True


@patch("app.engines.trade_selector.get_settings")
@patch("app.engines.trade_ranking.ftv_authorization_policy")
@patch("app.engines.trade_ranking.rank_entry_candidate")
def test_find_best_entry_requires_rank_one_when_best_only(
    mock_rank, mock_policy, mock_settings,
):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.engines.trade_ranking import FtvAuthorization
    from app.engines.trade_selector import EntryCandidate, find_best_entry
    from app.models.schemas import (
        AutoTraderState,
        Breadth,
        MarketPhase,
        Regime,
        Side,
        SpotChart,
        StrategyType,
        SymbolSnapshot,
    )

    IST = ZoneInfo("Asia/Kolkata")
    mock_settings.return_value = Settings(
        selector_best_only_enabled=True,
        ftv_elite_top_only_enabled=True,
        top_moments_only_enabled=False,
        explosion_elite_exploding_only=False,
    )
    mock_rank.return_value = {
        "grade": "A",
        "score": 80.0,
        "allocationRank": 2,
        "evidence": {"tier": "ELITE", "explosionScore": 80.0},
    }
    mock_policy.return_value = FtvAuthorization(
        mode=None,
        reason="allocation_rank_not_one",
    )

    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=70.0,
        spot=24200.0,
        atmStrike=24200.0,
        regime=Regime.TREND_EXPANSION,
        breadth=Breadth(bias="BULLISH", score=70.0, aligned=True),
        spotChart=SpotChart(direction="BULLISH"),
        explosionAlerts=[{
            "symbol": "NIFTY",
            "side": "CALL",
            "strike": 24200.0,
            "premium": 120.0,
            "tier": "ELITE",
            "tradeable": True,
            "explosionScore": 80.0,
            "velocity3s": 2.0,
            "velocity9s": 1.5,
            "ictBaseRelativeMovePct": 18.0,
            "localBaseMovePct": 18.0,
            "ictFlatThenVertical": True,
            "ictBreakout": True,
            "volumeAwaken": True,
        }],
    )

    with patch(
        "app.engines.trade_selector._explosion_candidates",
        return_value=[
            EntryCandidate(
                symbol="NIFTY",
                side=Side.CALL,
                strike=24200.0,
                premium=120.0,
                mode="explosion",
                tier="ELITE",
                score=80.0,
                snap=snap,
                strategy_type=StrategyType.EXPLOSIVE,
                confidence=80.0,
                tqs=70.0,
            ),
        ],
    ):
        result = find_best_entry({"NIFTY": snap}, AutoTraderState())

    assert result is None
    _, kwargs = mock_policy.call_args
    assert kwargs.get("require_allocation_rank_one") is True
