from datetime import datetime, timedelta, timezone

import jwt

from app import config


def test_token_success_returns_bearer_jwt(client):
    r = client.post("/api/v1/auth/token", json={"subscriberNo": "5551001", "password": "ayse-pw"})
    assert r.status_code == 200
    body = r.json()
    assert body["tokenType"] == "Bearer"
    claims = jwt.decode(body["accessToken"], config.JWT_SECRET, algorithms=["HS256"])
    assert claims["sub"] == "5551001" and claims["role"] == "subscriber"
    assert claims["iss"] == config.JWT_ISSUER  # needed by the gateway jwt plugin


def test_token_wrong_password_is_401(client):
    r = client.post("/api/v1/auth/token", json={"subscriberNo": "5551001", "password": "nope"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_token_unknown_subscriber_same_error_as_wrong_password(client):
    r = client.post("/api/v1/auth/token", json={"subscriberNo": "9999999", "password": "x"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_protected_route_without_token_is_401(client):
    r = client.post("/api/v1/payments", json={})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_garbage_token_is_401(client):
    r = client.get(
        "/api/v1/bills/5551001/2026/10/detailed", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert r.status_code == 401


def test_expired_token_is_401(client):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    token = jwt.encode(
        {"sub": "5551001", "role": "subscriber", "exp": past}, config.JWT_SECRET, algorithm="HS256"
    )
    r = client.get(
        "/api/v1/bills/5551001/2026/10/detailed", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 401
    assert "expired" in r.json()["error"]["message"].lower()


def test_token_signed_with_other_secret_is_rejected(client):
    token = jwt.encode({"sub": "ADMIN", "role": "admin"}, "attacker-secret-0123456789-0123456789", algorithm="HS256")
    r = client.post(
        "/api/v1/usage",
        json={"subscriberNo": "5551001", "month": 10, "year": 2026, "usageType": "Phone"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401
