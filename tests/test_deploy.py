"""Health check and the optional password, as the hosted app needs them."""

import base64

import pytest
from fastapi.testclient import TestClient

from delay_ai import api

client = TestClient(api.app)


def basic(password: str) -> dict[str, str]:
    token = base64.b64encode(f"demo:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_health_check():
    assert client.get("/api/health").json() == {"ok": True}


def test_open_without_a_password(monkeypatch):
    monkeypatch.setattr(api, "PASSWORD", "")
    assert client.post("/api/view", json={}).status_code == 200


@pytest.fixture
def protected(monkeypatch):
    monkeypatch.setattr(api, "PASSWORD", "s3cret")


def test_password_is_asked_for(protected):
    response = client.post("/api/view", json={})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic")


def test_wrong_and_malformed_passwords_are_refused(protected):
    assert client.post("/api/view", json={}, headers=basic("nope")).status_code == 401
    bad = {"Authorization": "Basic %%%not-base64"}
    assert client.post("/api/view", json={}, headers=bad).status_code == 401


def test_right_password_lets_you_in(protected):
    assert client.post("/api/view", json={}, headers=basic("s3cret")).status_code == 200


def test_health_check_needs_no_password(protected):
    assert client.get("/api/health").status_code == 200
