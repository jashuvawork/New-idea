from types import SimpleNamespace
from unittest.mock import MagicMock

from app.engines.paper_lab_base_rip import (
    build_index_base_rip_monitor,
    paper_lab_base_rip_active,
    paper_lab_base_rip_rank_bonus,
)


def test_paper_lab_base_rip_rank_bonus_near_base():
    s = MagicMock()
    s.paper_lab_base_rip_enabled = True
    s.paper_trading = True
    s.enable_live_trading = False
    s.paper_lab_base_rip_max_local_base_pct = 18.0
    s.paper_lab_base_rip_min_velocity_3s = 1.5
    s.paper_lab_base_rip_min_explosion_score = 50.0
    s.paper_lab_base_rip_rank_bonus = 22.0
    alert = {
        "localBasePct": 12.0,
        "velocity3s": 2.0,
        "tier": "ELITE",
        "explosionScore": 80,
    }
    assert paper_lab_base_rip_rank_bonus(alert, s) == 22.0
    alert["localBasePct"] = 40.0
    assert paper_lab_base_rip_rank_bonus(alert, s) == 0.0


def test_build_index_base_rip_monitor_empty():
    s = MagicMock()
    s.paper_lab_base_rip_enabled = True
    s.paper_trading = True
    s.enable_live_trading = False
    s.paper_lab_base_rip_max_local_base_pct = 18.0
    board = build_index_base_rip_monitor({}, settings=s)
    assert board["labActive"] is True
    assert board["indices"] == {}