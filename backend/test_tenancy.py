import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv

load_dotenv()
if "TEST_DATABASE_URL" in os.environ:
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
if "TEST_ADMIN_DATABASE_URL" in os.environ:
    os.environ["ADMIN_DATABASE_URL"] = os.environ["TEST_ADMIN_DATABASE_URL"]

import json
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient

from main import app
from database import SessionLocal, AdminSessionLocal, bind_session_to_tenant
from lenco_client import compute_lenco_webhook_signature, mock_lenco_client
from models import User, MenuItem, DrinkInventory, Order, OrderItem
from seed import seed, TENANT_A_ID, TENANT_B_ID

client = TestClient(app)


def _auth_header(login_data: dict) -> dict:
    return {"Authorization": f"Bearer {login_data['access_token']}"}


def _get_tokens():
    res_a_owner = client.post(
        "/api/auth/login",
        json={"tenant_slug": "aunts-lusaka", "username": "aunt", "password": "owner123"},
    )
    assert res_a_owner.status_code == 200
    a_owner = res_a_owner.json()

    res_a_cashier = client.post(
        "/api/auth/login",
        json={"tenant_slug": "aunts-lusaka", "username": "cashier1", "password": "cashier123"},
    )
    assert res_a_cashier.status_code == 200
    a_cashier = res_a_cashier.json()

    res_b_owner = client.post(
        "/api/auth/login",
        json={"tenant_slug": "boma-kitwe", "username": "aunt", "password": "owner123"},
    )
    assert res_b_owner.status_code == 200
    b_owner = res_b_owner.json()

    res_b_cashier = client.post(
        "/api/auth/login",
        json={"tenant_slug": "boma-kitwe", "username": "cashier1", "password": "cashier123"},
    )
    assert res_b_cashier.status_code == 200
    b_cashier = res_b_cashier.json()

    return a_owner, a_cashier, b_owner, b_cashier


def test_overlapping_usernames_and_menu_names_isolated():
    """Verify two tenants share identical usernames ('aunt', 'cashier1') and menu names without collision."""
    seed()
    a_owner, a_cashier, b_owner, b_cashier = _get_tokens()

    assert a_owner["id"] != b_owner["id"]
    assert a_cashier["id"] != b_cashier["id"]

    menu_a = client.get(
        "/api/menu", headers=_auth_header(a_owner)
    ).json()
    menu_b = client.get(
        "/api/menu", headers=_auth_header(b_owner)
    ).json()

    assert len(menu_a) == 10
    assert len(menu_b) == 10

    ids_a = {item["id"] for item in menu_a}
    ids_b = {item["id"] for item in menu_b}
    assert ids_a.isdisjoint(ids_b), "Menu item IDs leaked across tenants!"

    names_a = {item["name"] for item in menu_a}
    names_b = {item["name"] for item in menu_b}
    assert names_a == names_b, "Both tenants should have overlapping menu item names"


def test_cross_tenant_menu_and_inventory_isolation():
    """Tenant A cannot read or update Tenant B's menu items or drink inventory by guessing IDs."""
    seed()
    a_owner, _, b_owner, _ = _get_tokens()

    menu_b = client.get(
        "/api/menu", headers=_auth_header(b_owner)
    ).json()
    inv_b = client.get(
        "/api/inventory/drinks", headers=_auth_header(b_owner)
    ).json()

    b_menu_item_id = menu_b[0]["id"]
    b_drink_inv_id = inv_b[0]["id"]
    original_b_price = menu_b[0]["price_zmw"]
    original_b_stock = inv_b[0]["stock_quantity"]

    # Tenant A attempts to PATCH Tenant B's menu item -> must 404
    res_patch_menu = client.patch(
        f"/api/menu/{b_menu_item_id}",
        json={"price_zmw": 999.0, "is_available": False},
        headers=_auth_header(a_owner),
    )
    assert res_patch_menu.status_code == 404

    # Tenant A attempts to PATCH Tenant B's drink inventory -> must 404
    res_patch_inv = client.patch(
        f"/api/inventory/drinks/{b_drink_inv_id}",
        json={"stock_quantity": 0},
        headers=_auth_header(a_owner),
    )
    assert res_patch_inv.status_code == 404

    # Verify Tenant B's data is untouched
    menu_b_after = client.get(
        "/api/menu", headers=_auth_header(b_owner)
    ).json()
    inv_b_after = client.get(
        "/api/inventory/drinks", headers=_auth_header(b_owner)
    ).json()
    assert menu_b_after[0]["price_zmw"] == original_b_price
    assert inv_b_after[0]["stock_quantity"] == original_b_stock


def test_cross_tenant_order_and_payment_isolation():
    """Tenant A cannot create orders using Tenant B's menu items or cashiers, nor initiate/poll Tenant B's payments."""
    seed()
    a_owner, a_cashier, b_owner, b_cashier = _get_tokens()

    menu_a = client.get(
        "/api/menu", headers=_auth_header(a_cashier)
    ).json()
    menu_b = client.get(
        "/api/menu", headers=_auth_header(b_cashier)
    ).json()

    a_item_id = menu_a[0]["id"]
    b_item_id = menu_b[0]["id"]

    # 1. Tenant A tries to place an order referencing Tenant B's menu_item_id
    res_cross_item = client.post(
        "/api/orders",
        json={
            "payment_method": "cash",
            "items": [{"menu_item_id": b_item_id, "quantity": 1}],
        },
        headers=_auth_header(a_cashier),
    )
    assert res_cross_item.status_code == 404

    # 2. Tenant A tries to pass cashier_id in body (rejected with 422 due to extra="forbid")
    res_cross_cashier = client.post(
        "/api/orders",
        json={
            "cashier_id": b_cashier["id"],
            "payment_method": "cash",
            "items": [{"menu_item_id": a_item_id, "quantity": 1}],
        },
        headers=_auth_header(a_cashier),
    )
    assert res_cross_cashier.status_code == 422

    # 3. Tenant B creates a valid pending mobile_money order
    res_b_order = client.post(
        "/api/orders",
        json={
            "payment_method": "mobile_money",
            "items": [{"menu_item_id": b_item_id, "quantity": 2}],
        },
        headers=_auth_header(b_cashier),
    )
    assert res_b_order.status_code == 201
    b_order_id = res_b_order.json()["id"]
    assert res_b_order.json()["cashier_id"] == b_cashier["id"]

    # 4. Tenant A tries to initiate mobile money payment for Tenant B's order_id -> 404
    res_cross_init = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": b_order_id, "phone": "0977123456", "operator": "airtel"},
        headers=_auth_header(a_cashier),
    )
    assert res_cross_init.status_code == 404

    # 5. Tenant B initiates mobile money payment
    res_b_init = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": b_order_id, "phone": "0977123456", "operator": "airtel"},
        headers=_auth_header(b_cashier),
    )
    assert res_b_init.status_code == 200
    b_lenco_ref = res_b_init.json()["lenco_reference"]

    # 6. Tenant A tries to poll Tenant B's payment with Tenant A's token -> 404
    res_cross_poll = client.get(
        f"/api/payments/status/{b_lenco_ref}",
        headers=_auth_header(a_cashier),
    )
    assert res_cross_poll.status_code == 404

    # Also create a pending mobile money order in Tenant A and verify Tenant B's webhook cannot affect Tenant A's order
    res_a_order = client.post(
        "/api/orders",
        json={
            "payment_method": "mobile_money",
            "items": [{"menu_item_id": a_item_id, "quantity": 1}],
        },
        headers=_auth_header(a_cashier),
    )
    assert res_a_order.status_code == 201
    a_order_id = res_a_order.json()["id"]
    res_a_init = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": a_order_id, "phone": "0977123456", "operator": "airtel"},
        headers=_auth_header(a_cashier),
    )
    a_lenco_ref = res_a_init.json()["lenco_reference"]

    # 7. Complete Tenant B's order via signed Lenco webhook and verify Tenant A's order/dashboard/calendar are untouched
    mock_lenco_client.set_collection_state(b_lenco_ref, status="successful")
    raw_b_webhook = json.dumps(
        {
            "event": "collection.successful",
            "data": {"reference": b_lenco_ref, "status": "successful"},
        }
    ).encode("utf-8")
    res_b_webhook = client.post(
        "/api/webhooks/lenco",
        content=raw_b_webhook,
        headers={
            "Content-Type": "application/json",
            "X-Lenco-Signature": compute_lenco_webhook_signature(raw_b_webhook),
        },
    )
    assert res_b_webhook.status_code == 200

    # Tenant A's pending order is still pending
    res_a_poll = client.get(
        f"/api/payments/status/{a_lenco_ref}",
        headers=_auth_header(a_cashier),
    )
    assert res_a_poll.status_code == 200
    assert res_a_poll.json()["payment_status"] == "pending"

    summary_a = client.get(
        "/api/dashboard/summary", headers=_auth_header(a_owner)
    ).json()
    summary_b = client.get(
        "/api/dashboard/summary", headers=_auth_header(b_owner)
    ).json()

    assert summary_a["today_orders_count"] == 0
    assert summary_a["today_total_revenue_zmw"] == 0.0
    assert summary_a["settlement_account_balance_zmw"] == 0.0

    assert summary_b["today_orders_count"] == 1
    assert summary_b["today_total_revenue_zmw"] > 0

    cal_a = client.get(
        "/api/dashboard/calendar", headers=_auth_header(a_owner)
    ).json()
    cal_b = client.get(
        "/api/dashboard/calendar", headers=_auth_header(b_owner)
    ).json()
    assert cal_a == []
    assert len(cal_b) == 1


def test_database_composite_foreign_keys_and_rls_enforcement():
    """Verify Postgres RLS blocks unscoped/cross-tenant queries and composite FKs reject cross-tenant references at DB level."""
    seed()

    # 1. Verify connecting as `bomapos_app` (SessionLocal) without setting app.current_tenant returns 0 rows due to RLS
    unscoped_db = SessionLocal()
    try:
        rows = unscoped_db.execute(text("SELECT count(*) FROM menu_items")).scalar()
        assert rows == 0, f"RLS failed: expected 0 rows without app.current_tenant, got {rows}"

        user_rows = unscoped_db.execute(text("SELECT count(*) FROM users")).scalar()
        assert user_rows == 0, f"RLS failed on users: expected 0 rows, got {user_rows}"
    finally:
        unscoped_db.close()

    # 2. Verify composite FK prevents inserting an order for Tenant A referencing Tenant B's cashier even as schema owner
    admin_db = AdminSessionLocal()
    try:
        user_b = (
            admin_db.query(User)
            .filter(User.tenant_id == TENANT_B_ID, User.username == "cashier1")
            .first()
        )
        item_b = (
            admin_db.query(MenuItem)
            .filter(MenuItem.tenant_id == TENANT_B_ID)
            .first()
        )

        # Attempt cross-tenant order (tenant_id=A, cashier_id=B) -> must fail fk_orders_cashier_tenant
        bad_order = Order(
            tenant_id=TENANT_A_ID,
            cashier_id=user_b.id,
            total_ngwee=1000,
            payment_method="cash",
            payment_status="paid",
        )
        admin_db.add(bad_order)
        with pytest.raises(IntegrityError):
            admin_db.commit()
        admin_db.rollback()

        # Attempt cross-tenant drink_inventory (tenant_id=A, menu_item_id=B) -> must fail fk_drink_inventories_menu_item_tenant
        bad_inv = DrinkInventory(
            tenant_id=TENANT_A_ID,
            menu_item_id=item_b.id,
            stock_quantity=10,
            low_stock_threshold=5,
        )
        admin_db.add(bad_inv)
        with pytest.raises(IntegrityError):
            admin_db.commit()
        admin_db.rollback()
    finally:
        admin_db.close()

