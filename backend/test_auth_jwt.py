import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv

load_dotenv()
if "TEST_DATABASE_URL" in os.environ:
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
if "TEST_ADMIN_DATABASE_URL" in os.environ:
    os.environ["ADMIN_DATABASE_URL"] = os.environ["TEST_ADMIN_DATABASE_URL"]

import jwt
import pytest
from fastapi.testclient import TestClient

from main import (
    app,
    JWT_SECRET,
    JWT_ALGORITHM,
    hash_refresh_token,
    validate_jwt_secret,
    parse_allowed_origins,
    reset_login_rate_limiter,
)
from database import AdminSessionLocal
from models import Tenant, User, RefreshToken
from seed import seed, TENANT_A_ID

client = TestClient(app)


def test_jwt_claims_and_signature_verification():
    """Verify issued JWT contains sub, tenant_id, role, exp, iat, jti and rejects forged/unsigned/legacy tokens."""
    seed()
    reset_login_rate_limiter()

    res = client.post(
        "/api/auth/login",
        json={"tenant_slug": "aunts-lusaka", "username": "aunt", "password": "owner123"},
    )
    assert res.status_code == 200
    data = res.json()

    # Verify required JWT claims on access_token
    decoded = jwt.decode(data["access_token"], JWT_SECRET, algorithms=[JWT_ALGORITHM])
    for claim in ("sub", "tenant_id", "role", "exp", "iat", "jti"):
        assert claim in decoded, f"Missing required claim: {claim}"
    assert decoded["sub"] == str(data["id"])
    assert decoded["tenant_id"] == str(TENANT_A_ID)
    assert decoded["role"] == "owner"

    # 1. Legacy "id:role:username" token rejected
    res_legacy = client.get(
        "/api/menu",
        headers={"Authorization": f"Bearer {data['id']}:owner:aunt"},
    )
    assert res_legacy.status_code == 401

    # 2. Forged token signed with wrong secret rejected
    now = datetime.now(timezone.utc)
    forged_token = jwt.encode(
        {
            "sub": str(data["id"]),
            "tenant_id": str(TENANT_A_ID),
            "role": "owner",
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=30)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        "wrong-secret-key-that-is-at-least-32-bytes-long",
        algorithm="HS256",
    )
    res_forged = client.get(
        "/api/menu",
        headers={"Authorization": f"Bearer {forged_token}"},
    )
    assert res_forged.status_code == 401

    # 3. Unsigned token (alg="none") rejected
    unsigned_token = jwt.encode(
        {
            "sub": str(data["id"]),
            "tenant_id": str(TENANT_A_ID),
            "role": "owner",
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=30)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        "",
        algorithm="none",
    )
    res_unsigned = client.get(
        "/api/menu",
        headers={"Authorization": f"Bearer {unsigned_token}"},
    )
    assert res_unsigned.status_code == 401


def test_expired_jwt_rejected():
    """Verify an expired access token is rejected with 401."""
    seed()
    reset_login_rate_limiter()

    res = client.post(
        "/api/auth/login",
        json={"tenant_slug": "aunts-lusaka", "username": "aunt", "password": "owner123"},
    )
    data = res.json()

    past = datetime.now(timezone.utc) - timedelta(minutes=31)
    expired_token = jwt.encode(
        {
            "sub": str(data["id"]),
            "tenant_id": str(TENANT_A_ID),
            "role": "owner",
            "type": "access",
            "iat": int((past - timedelta(minutes=30)).timestamp()),
            "exp": int(past.timestamp()),
            "jti": str(uuid.uuid4()),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )

    res_exp = client.get(
        "/api/menu",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res_exp.status_code == 401
    assert "expired" in res_exp.json()["detail"].lower()


def test_refresh_token_rotation_hash_storage_and_logout_revocation():
    """Verify refresh tokens are stored only as hashes, rotate on refresh, and fail after rotation or logout."""
    seed()
    reset_login_rate_limiter()

    res = client.post(
        "/api/auth/login",
        json={"tenant_slug": "aunts-lusaka", "username": "cashier1", "password": "cashier123"},
    )
    assert res.status_code == 200
    login_data = res.json()
    raw_refresh_1 = login_data["refresh_token"]
    expected_hash_1 = hash_refresh_token(raw_refresh_1)

    # Verify only the SHA-256 hash is stored in DB, never the raw token
    admin_db = AdminSessionLocal()
    try:
        db_row = (
            admin_db.query(RefreshToken)
            .filter(RefreshToken.token_hash == expected_hash_1)
            .first()
        )
        assert db_row is not None
        assert db_row.token_hash != raw_refresh_1
        assert db_row.revoked_at is None
    finally:
        admin_db.close()

    # Rotate refresh token
    res_refresh = client.post(
        "/api/auth/refresh",
        json={"refresh_token": raw_refresh_1},
    )
    assert res_refresh.status_code == 200
    rotated = res_refresh.json()
    assert rotated["access_token"]
    assert rotated["refresh_token"]
    assert rotated["refresh_token"] != raw_refresh_1

    # Re-using the old rotated refresh token must fail with 401
    res_reuse = client.post(
        "/api/auth/refresh",
        json={"refresh_token": raw_refresh_1},
    )
    assert res_reuse.status_code == 401

    # New access token works
    res_menu = client.get(
        "/api/menu",
        headers={"Authorization": f"Bearer {rotated['access_token']}"},
    )
    assert res_menu.status_code == 200

    # Logout revokes the new refresh token
    res_logout = client.post(
        "/api/auth/logout",
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert res_logout.status_code == 200

    # Using the revoked refresh token after logout fails with 401
    res_after_logout = client.post(
        "/api/auth/refresh",
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert res_after_logout.status_code == 401


def test_inactive_user_and_suspended_tenant_rejected():
    """Verify get_current_user checks user.is_active and tenant.status == 'active'."""
    seed()
    reset_login_rate_limiter()

    res = client.post(
        "/api/auth/login",
        json={"tenant_slug": "aunts-lusaka", "username": "cashier1", "password": "cashier123"},
    )
    token = res.json()["access_token"]
    user_id = res.json()["id"]

    # Deactivate user in DB -> token must immediately fail with 401
    admin_db = AdminSessionLocal()
    try:
        user = admin_db.query(User).filter(User.id == user_id).first()
        user.is_active = False
        admin_db.commit()

        res_inactive = client.get(
            "/api/menu",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_inactive.status_code == 401

        # Re-activate user, suspend tenant -> token must fail with 403
        user.is_active = True
        tenant = admin_db.query(Tenant).filter(Tenant.id == TENANT_A_ID).first()
        tenant.status = "suspended"
        admin_db.commit()

        res_suspended = client.get(
            "/api/menu",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_suspended.status_code == 403

        # Restore tenant status
        tenant.status = "active"
        admin_db.commit()
    finally:
        admin_db.close()


def test_protected_endpoints_require_auth_and_cashier_cannot_hit_owner_routes():
    """Verify GET /api/menu, GET /api/inventory/drinks, GET /api/payments/status require auth, and cashier cannot hit owner routes."""
    seed()
    reset_login_rate_limiter()

    # Unauthenticated calls must return 401
    assert client.get("/api/menu").status_code == 401
    assert client.get("/api/inventory/drinks").status_code == 401
    assert client.get("/api/payments/status/LENCO-ZMW-FAKE1234").status_code == 401

    res_cashier = client.post(
        "/api/auth/login",
        json={"tenant_slug": "aunts-lusaka", "username": "cashier1", "password": "cashier123"},
    )
    cashier_headers = {"Authorization": f"Bearer {res_cashier.json()['access_token']}"}

    # Cashier can read menu & drink inventory
    menu = client.get("/api/menu", headers=cashier_headers).json()
    inv = client.get("/api/inventory/drinks", headers=cashier_headers).json()
    assert len(menu) > 0
    assert len(inv) > 0

    # Cashier cannot hit owner-only routes (403)
    assert client.get("/api/dashboard/summary", headers=cashier_headers).status_code == 403
    assert client.get("/api/dashboard/calendar", headers=cashier_headers).status_code == 403
    assert (
        client.patch(
            f"/api/menu/{menu[0]['id']}",
            json={"price_zmw": 50.0, "is_available": True},
            headers=cashier_headers,
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/inventory/drinks/{inv[0]['id']}",
            json={"stock_quantity": 99},
            headers=cashier_headers,
        ).status_code
        == 403
    )


def test_login_rate_limiting_and_startup_config_validation():
    """Verify login rate limiting returns 429 after repeated failures and config validators reject unsafe values."""
    seed()
    reset_login_rate_limiter()

    for _ in range(5):
        r = client.post(
            "/api/auth/login",
            json={"tenant_slug": "aunts-lusaka", "username": "aunt", "password": "wrong-password"},
        )
        assert r.status_code == 401

    r_limited = client.post(
        "/api/auth/login",
        json={"tenant_slug": "aunts-lusaka", "username": "aunt", "password": "wrong-password"},
    )
    assert r_limited.status_code == 429
    reset_login_rate_limiter()

    # Startup validation checks
    with pytest.raises(RuntimeError):
        validate_jwt_secret("")
    with pytest.raises(RuntimeError):
        validate_jwt_secret("too-short-secret")
    with pytest.raises(RuntimeError):
        parse_allowed_origins("*")
    with pytest.raises(RuntimeError):
        parse_allowed_origins("")


def test_lenco_webhook_rejects_unsigned_requests():
    """Verify /api/webhooks/lenco rejects unsigned requests with 401."""
    seed()
    res = client.post(
        "/api/webhooks/lenco",
        json={"event": "collection.successful", "data": {"reference": "unsigned-ref", "status": "successful"}},
    )
    assert res.status_code == 401

def test_login_missing_tenant_slug_returns_generic_401():
    """Verify login without tenant_slug or with empty slug returns generic 401."""
    seed()
    reset_login_rate_limiter()

    # 1. Missing tenant_slug field entirely
    res1 = client.post(
        "/api/auth/login",
        json={"username": "aunt", "password": "owner123"},
    )
    assert res1.status_code == 401
    assert res1.json()["detail"] == "Invalid tenant, username, or password"

    # 2. Empty tenant_slug string
    res2 = client.post(
        "/api/auth/login",
        json={"tenant_slug": "", "username": "aunt", "password": "owner123"},
    )
    assert res2.status_code == 401
    assert res2.json()["detail"] == "Invalid tenant, username, or password"

    # 3. Whitespace-only tenant_slug
    res3 = client.post(
        "/api/auth/login",
        json={"tenant_slug": "   ", "username": "aunt", "password": "owner123"},
    )
    assert res3.status_code == 401
    assert res3.json()["detail"] == "Invalid tenant, username, or password"


def test_refresh_token_reuse_detection_revokes_all_user_tokens():
    """Presenting an already-revoked refresh token revokes all active refresh tokens for that user and returns 401."""
    seed()
    reset_login_rate_limiter()

    # Step 1: User logs in and receives refresh token 1
    res_login = client.post(
        "/api/auth/login",
        json={"tenant_slug": "aunts-lusaka", "username": "cashier1", "password": "cashier123"},
    )
    assert res_login.status_code == 200
    token1 = res_login.json()["refresh_token"]

    # Step 2: User rotates token 1 -> receives refresh token 2
    res_rotate = client.post(
        "/api/auth/refresh",
        json={"refresh_token": token1},
    )
    assert res_rotate.status_code == 200
    token2 = res_rotate.json()["refresh_token"]

    # Verify in DB: token 1 is revoked, token 2 is active
    admin_db = AdminSessionLocal()
    try:
        row1 = admin_db.query(RefreshToken).filter(RefreshToken.token_hash == hash_refresh_token(token1)).first()
        row2 = admin_db.query(RefreshToken).filter(RefreshToken.token_hash == hash_refresh_token(token2)).first()
        assert row1 is not None and row1.revoked_at is not None
        assert row2 is not None and row2.revoked_at is None
    finally:
        admin_db.close()

    # Step 3: Adversary attempts to reuse already-revoked token 1
    res_reuse = client.post(
        "/api/auth/refresh",
        json={"refresh_token": token1},
    )
    assert res_reuse.status_code == 401

    # Step 4: Verify in DB: ALL active refresh tokens for this user are now revoked
    admin_db = AdminSessionLocal()
    try:
        row2_after = admin_db.query(RefreshToken).filter(RefreshToken.token_hash == hash_refresh_token(token2)).first()
        assert row2_after is not None
        assert row2_after.revoked_at is not None, "Token 2 must be revoked by reuse detection!"
    finally:
        admin_db.close()

    # Step 5: Legitimate user attempting to use token 2 now fails with 401
    res_token2_fail = client.post(
        "/api/auth/refresh",
        json={"refresh_token": token2},
    )
    assert res_token2_fail.status_code == 401


def test_rate_limiter_trust_proxy_and_pruning():
    """Verify rate limiter extracts client IP via X-Forwarded-For when TRUST_PROXY=true, and prunes expired keys."""
    import time
    from main import _login_attempts, _prune_expired_login_attempts

    reset_login_rate_limiter()

    # 1. Without TRUST_PROXY, X-Forwarded-For is ignored
    os.environ["TRUST_PROXY"] = "false"
    res1 = client.post(
        "/api/auth/login",
        headers={"X-Forwarded-For": "203.0.113.195, 70.41.3.18"},
        json={"tenant_slug": "aunts-lusaka", "username": "aunt", "password": "wrong-password"},
    )
    assert res1.status_code == 401
    # Key in _login_attempts should use "testclient" (TestClient default host), not "203.0.113.195"
    assert not any("203.0.113.195" in k for k in _login_attempts.keys())

    # 2. With TRUST_PROXY=true, first hop in X-Forwarded-For is used
    reset_login_rate_limiter()
    os.environ["TRUST_PROXY"] = "true"
    res2 = client.post(
        "/api/auth/login",
        headers={"X-Forwarded-For": "203.0.113.195, 70.41.3.18"},
        json={"tenant_slug": "aunts-lusaka", "username": "aunt", "password": "wrong-password"},
    )
    assert res2.status_code == 401
    expected_prefix = "203.0.113.195:aunts-lusaka:aunt"
    assert expected_prefix in _login_attempts
    assert len(_login_attempts[expected_prefix]) == 1

    # 3. Test pruning of expired entries
    now = time.monotonic()
    # Inject expired entry
    _login_attempts["stale-client:tenant:user"] = [now - 120.0]
    assert "stale-client:tenant:user" in _login_attempts

    # Prune should remove the stale key
    _prune_expired_login_attempts(now)
    assert "stale-client:tenant:user" not in _login_attempts
    assert expected_prefix in _login_attempts

    # Clean up environment
    os.environ["TRUST_PROXY"] = "false"
    reset_login_rate_limiter()
