"""Daily profit calibration — block weak sides/buckets."""

from collections import defaultdict
from typing import Any

from app.models.schemas import DailyReport, PaperTrade, Side


class DailyCalibration:
    """Block sides with 0 wins when PF is weak."""

    def __init__(self):
        self._side_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "losses": 0})
        self._bucket_blocks: dict[str, bool] = {}

    def record_trade(self, trade: PaperTrade) -> None:
        side = trade.side.value
        if trade.pnlInr > 0:
            self._side_stats[side]["wins"] += 1
            # Recovering — ease loss pressure after a win on this side
            if self._side_stats[side]["losses"] > 0:
                self._side_stats[side]["losses"] -= 1
        elif trade.pnlInr < 0:
            self._side_stats[side]["losses"] += 1

    def get_blocks(self) -> dict[str, bool]:
        from app.config import get_settings

        min_losses = get_settings().calibration_block_min_losses
        blocks = {"CALL": False, "PUT": False}
        for side in ("CALL", "PUT"):
            stats = self._side_stats[side]
            if stats["losses"] >= min_losses and stats["wins"] == 0:
                blocks[side] = True
        return blocks

    def should_reset(self, blocks: dict[str, bool]) -> bool:
        return blocks.get("CALL") and blocks.get("PUT")

    def reset(self) -> None:
        self._side_stats.clear()
        self._bucket_blocks.clear()

    def build_report(self, closed: list[PaperTrade]) -> DailyReport:
        wins = losses = scratches = 0
        gross_profit = gross_loss = 0.0
        exit_reasons: dict[str, int] = defaultdict(int)

        for t in closed:
            exit_reasons[t.exitReason or "unknown"] += 1
            if t.pnlInr > 0:
                wins += 1
                gross_profit += t.pnlInr
            elif t.pnlInr < 0:
                losses += 1
                gross_loss += abs(t.pnlInr)
            else:
                scratches += 1

        total = wins + losses
        pf = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0)
        net = gross_profit - gross_loss
        wr = (wins / total * 100) if total > 0 else 0

        return DailyReport(
            wins=wins,
            losses=losses,
            scratches=scratches,
            profitFactor=round(pf, 2),
            netPnlInr=round(net, 2),
            winRate=round(wr, 1),
            exitReasons=dict(exit_reasons),
        )

    def performance_analysis(self, closed: list[PaperTrade]) -> dict[str, Any]:
        by_side: dict[str, Any] = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
        by_bucket: dict[str, Any] = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})

        for t in closed:
            side = t.side.value
            bucket = t.strategyType.value
            if t.pnlInr > 0:
                by_side[side]["wins"] += 1
                by_bucket[bucket]["wins"] += 1
            elif t.pnlInr < 0:
                by_side[side]["losses"] += 1
                by_bucket[bucket]["losses"] += 1
            by_side[side]["pnl"] += t.pnlInr
            by_bucket[bucket]["pnl"] += t.pnlInr

        return {
            "bySide": dict(by_side),
            "byBucket": dict(by_bucket),
            "totalTrades": len(closed),
            "calibrationBlocks": self.get_blocks(),
        }
