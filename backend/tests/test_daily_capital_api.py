"""Daily capital GET/POST on auto-trader API."""

from fastapi.testclient import TestClient

from app.engines.capital_allocator import reset_capital_for_tests
from app.main import app


def test_auto_trader_capital_get_and_post():
    reset_capital_for_tests()
    client = TestClient(app)
    post = client.post("/api/auto-trader/capital", json={"allocatedInr": 45_000})
    assert post.status_code == 200
    body = post.json()
    assert body["requestedInr"] == 45_000
    assert body["allocatedInr"] == 45_000
    assert body["runtime"]["availableMarginInr"] == 45_000

    get = client.get("/api/auto-trader/capital")
    assert get.status_code == 200
    snap = get.json()
    assert snap["runtime"]["availableMarginInr"] == 45_000
    assert snap["env"]["fallbackCapitalInr"] > 0
    assert "aligned" in snap