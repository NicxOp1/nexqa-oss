import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from webhook_server.app import app
from webhook_server.auth import verify_retell_signature
from webhook_server.config import settings

KEY = "test_retell_key"


def _sign(body: str, key: str = KEY, ts: int | None = None) -> str:
    ts = int(time.time() * 1000) if ts is None else ts
    digest = hmac.new(key.encode(), (body + str(ts)).encode(), hashlib.sha256).hexdigest()
    return f"v={ts},d={digest}"


def test_valid_signature_passes():
    body = '{"name":"check_availability"}'
    assert verify_retell_signature(body, _sign(body), KEY)


@pytest.mark.parametrize(
    "signature",
    [None, "", "garbage", "v=1,d=abc"],
)
def test_malformed_signature_fails(signature):
    assert not verify_retell_signature("{}", signature, KEY)


def test_wrong_key_or_tampered_body_fails():
    body = '{"a":1}'
    assert not verify_retell_signature(body, _sign(body, key="other"), KEY)
    assert not verify_retell_signature('{"a":2}', _sign(body), KEY)


def test_stale_signature_fails():
    body = "{}"
    old = int(time.time() * 1000) - 10 * 60 * 1000
    assert not verify_retell_signature(body, _sign(body, ts=old), KEY)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "verify_signatures", True)
    monkeypatch.setattr(settings, "retell_api_key", KEY)
    monkeypatch.setattr(settings, "retell_webhook_key", None)
    monkeypatch.setattr(settings, "admin_token", "")
    return TestClient(app)


def test_unsigned_webhook_is_rejected(client):
    resp = client.post("/webhook/agent_1", content=json.dumps({"name": "x"}))
    assert resp.status_code == 401


def test_signed_webhook_reaches_handler(client, monkeypatch):
    async def no_agent(agent_id):
        return None

    monkeypatch.setattr("webhook_server.router.get_agent_config", no_agent)
    body = json.dumps({"function_name": "check_availability", "arguments": {}})
    resp = client.post(
        "/webhook/agent_1", content=body, headers={"x-retell-signature": _sign(body)}
    )
    assert resp.status_code == 200
    assert "trouble" in resp.json()["result"]


def test_admin_endpoint_is_off_without_token(client):
    assert client.post("/admin/refresh-cache").status_code == 404


def test_admin_endpoint_requires_bearer_token(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    monkeypatch.setattr("webhook_server.router.refresh_cache", _noop)
    assert client.post("/admin/refresh-cache").status_code == 401
    ok = client.post("/admin/refresh-cache", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200


async def _noop():
    return None


def test_health_is_public(client):
    assert client.get("/health").json()["status"] == "ok"
