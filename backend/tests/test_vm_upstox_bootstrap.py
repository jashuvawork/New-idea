"""VM Upstox prod token sync (paper lab)."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.services import upstox_vm_bootstrap
from tests.mock_defaults import settings_mock


@pytest.fixture
def client(monkeypatch):
    s = settings_mock()
    s.paper_lab_vm_token_sync_export_enabled = True
    s.paper_lab_vm_token_sync_key = "test-sync-key"
    monkeypatch.setattr("app.routers.paper_lab.get_settings", lambda: s)
    monkeypatch.setattr("app.config.get_settings", lambda: s)
    return TestClient(create_app())


def test_vm_export_disabled_returns_404(client, monkeypatch):
    s = settings_mock()
    s.paper_lab_vm_token_sync_export_enabled = False
    monkeypatch.setattr("app.routers.paper_lab.get_settings", lambda: s)

    resp = client.get("/api/paper-lab/vm-upstox-session", headers={"X-Paper-Lab-VM-Sync-Key": "x"})
    assert resp.status_code == 404


def test_vm_export_bad_key_401(client):
    resp = client.get("/api/paper-lab/vm-upstox-session", headers={"X-Paper-Lab-VM-Sync-Key": "wrong"})
    assert resp.status_code == 401


def test_sync_from_prod_missing_key(monkeypatch):
    s = settings_mock()
    s.paper_lab_prod_api_base = "http://example.com"
    s.paper_lab_vm_token_sync_key = ""
    monkeypatch.setattr(upstox_vm_bootstrap, "get_settings", lambda: s)
    out = asyncio.run(upstox_vm_bootstrap.sync_upstox_session_from_prod())
    assert out["ok"] is False
    assert out["error"] == "missing_paper_lab_vm_token_sync_key"


def test_bootstrap_skips_when_disabled(monkeypatch):
    s = settings_mock()
    s.vm_upstox_local_enabled = False
    monkeypatch.setattr(upstox_vm_bootstrap, "get_settings", lambda: s)
    out = asyncio.run(upstox_vm_bootstrap.maybe_bootstrap_vm_upstox())
    assert out["bootstrapped"] is False
    assert out["reason"] == "vm_upstox_local_disabled"


def test_direct_bootstrap_missing_code(monkeypatch):
    s = settings_mock()
    s.vm_upstox_direct_oauth_enabled = True
    s.upstox_oauth_code = ""
    s.upstox_bootstrap_access_token = ""
    monkeypatch.setattr(upstox_vm_bootstrap, "get_settings", lambda: s)
    async def _no_token():
        return False

    monkeypatch.setattr(upstox_vm_bootstrap, "has_upstox_token", _no_token)
    out = asyncio.run(upstox_vm_bootstrap.maybe_bootstrap_direct_upstox())
    assert out["bootstrapped"] is False
    assert out["reason"] == "missing_oauth_code_or_bootstrap_token"