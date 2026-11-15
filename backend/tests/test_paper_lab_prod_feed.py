from unittest.mock import MagicMock

from app.engines.paper_lab_prod_feed import paper_lab_active


def test_paper_lab_active_requires_flags():
    s = MagicMock()
    s.enable_live_trading = False
    s.paper_trading = True
    s.paper_lab_use_prod_snapshots = True
    s.paper_lab_prod_api_base = "https://api.example.com"
    assert paper_lab_active(s) is True

    s.enable_live_trading = True
    assert paper_lab_active(s) is False