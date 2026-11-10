import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv

load_dotenv()
if "TEST_DATABASE_URL" in os.environ:
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
if "TEST_ADMIN_DATABASE_URL" in os.environ:
    os.environ["ADMIN_DATABASE_URL"] = os.environ["TEST_ADMIN_DATABASE_URL"]

import httpx
from fastapi.testclient import TestClient
from main import (
    app,
    reset_login_rate_limiter,
    reconcile_all_tenants_stuck_orders,
)
from database import SessionLocal, bind_session_to_tenant
from lenco_client import (
    LiveLencoClient,
    compute_lenco_webhook_signature,
    mock_lenco_client,
)
from models import DrinkInventory, MenuItem, Order, OrderItem
from money import ngwee_to_zmw, zmw_to_ngwee
from seed import seed, TENANT_A_ID, TENANT_B_ID

client = TestClient(app)
LUSAKA_TZ = ZoneInfo("Africa/Lusaka")


def _post_signed_lenco_webhook(payload_dict: dict, signature_override: str = None):
    raw_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = (
        signature_override
        if signature_override is not None
        else compute_lenco_webhook_signature(raw_bytes)
    )
    return client.post(
        "/api/webhooks/lenco",
        content=raw_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Lenco-Signature": sig,
        },
    )


def test_payments_and_analytics_workflow():
    print("Resetting database to initial clean state...")
    seed()
    reset_login_rate_limiter()

    print("\n--- 1. Authenticate Cashier & Owner ---")
    res_cashier = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "aunts-lusaka",
            "username": "cashier1",
            "password": "cashier123",
        },
    )
    assert res_cashier.status_code == 200
    cashier_token = res_cashier.json()["access_token"]
    cashier_id = res_cashier.json()["id"]

    res_owner = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "aunts-lusaka",
            "username": "aunt",
            "password": "owner123",
        },
    )
    assert res_owner.status_code == 200
    owner_token = res_owner.json()["access_token"]
    print("Auth OK: Cashier & Owner tokens retrieved.")

    print("\n--- 2. Create Mobile Money Order with Meal & Drink ---")
    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    meal = db.query(MenuItem).filter(MenuItem.category == "meal").first()
    meal_id = meal.id
    meal_price_ngwee = meal.price_ngwee

    drink = db.query(MenuItem).filter(MenuItem.name.like("%Castle Lite%")).first()
    drink_id = drink.id
    drink_name = drink.name
    drink_price_ngwee = drink.price_ngwee

    drink_inv = (
        db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == drink_id).first()
    )
    initial_drink_stock = drink_inv.stock_quantity
    db.close()

    print(f"Target Drink: {drink_name} | Initial Stock: {initial_drink_stock}")

    order_payload = {
        "payment_method": "mobile_money",
        "items": [
            {"menu_item_id": meal_id, "quantity": 2},
            {"menu_item_id": drink_id, "quantity": 3},
        ],
    }

    res_order = client.post(
        "/api/orders",
        json=order_payload,
        headers={"Authorization": f"Bearer {cashier_token}"},
    )
    assert res_order.status_code == 201, f"Failed: {res_order.text}"
    order_data = res_order.json()
    order_id = order_data["id"]
    expected_total = ngwee_to_zmw(meal_price_ngwee * 2 + drink_price_ngwee * 3)

    print(
        f"Created Order #{order_id} | Status: {order_data['payment_status']} | Total: ZMW {order_data['total_amount']}"
    )
    assert order_data["cashier_id"] == cashier_id
    assert order_data["payment_status"] == "pending"
    assert order_data["total_amount"] == expected_total

    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    drink_inv_check = (
        db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == drink_id).first()
    )
    assert (
        drink_inv_check.stock_quantity == initial_drink_stock
    ), "Stock should NOT decrease while order is pending"
    db.close()
    print("Pending order stock check OK: Stock unchanged.")

    print("\n--- 3. Testing Phone Validation & Payment Initiation ---")
    res_bad_phone = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "12345", "operator": "airtel"},
        headers={"Authorization": f"Bearer {cashier_token}"},
    )
    assert res_bad_phone.status_code == 400
    print("Phone validation check OK: Bad phone rejected with HTTP 400.")

    res_initiate = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "0977123456", "operator": "airtel"},
        headers={"Authorization": f"Bearer {cashier_token}"},
    )
    assert res_initiate.status_code == 200, f"Failed: {res_initiate.text}"
    init_data = res_initiate.json()
    lenco_ref = init_data["lenco_reference"]
    print(f"Initiation OK: Reference generated -> {lenco_ref}")
    assert not lenco_ref.startswith("BOMA-")
    assert uuid.UUID(lenco_ref).version == 4

    print("\n--- 4. Polling Fallback Before Webhook ---")
    res_poll_pre = client.get(
        f"/api/payments/status/{lenco_ref}",
        headers={"Authorization": f"Bearer {cashier_token}"},
    )
    assert res_poll_pre.status_code == 200
    assert res_poll_pre.json()["payment_status"] == "pending"
    print("Polling check OK: Returns pending.")

    print("\n--- 5. Trigger Signed Lenco Webhook (collection.successful) ---")
    mock_lenco_client.set_collection_state(lenco_ref, status="successful")
    webhook_payload = {
        "event": "collection.successful",
        "data": {
            "reference": lenco_ref,
            "status": "successful",
            "amount": f"{expected_total:.2f}",
            "currency": "ZMW",
        },
    }
    res_webhook = _post_signed_lenco_webhook(webhook_payload)
    assert res_webhook.status_code == 200
    print("Webhook responded:", res_webhook.json())

    res_poll_post = client.get(
        f"/api/payments/status/{lenco_ref}",
        headers={"Authorization": f"Bearer {cashier_token}"},
    )
    assert res_poll_post.status_code == 200
    assert res_poll_post.json()["payment_status"] == "paid"
    print("Order status is now 'paid': OK!")

    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    drink_inv_after = (
        db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == drink_id).first()
    )
    expected_stock = initial_drink_stock - 3
    print(
        f"Drink Stock After Payment: {drink_inv_after.stock_quantity} (Expected: {expected_stock})"
    )
    assert drink_inv_after.stock_quantity == expected_stock
    db.close()
    print("Stock deduction check OK!")

    print("\n--- 6. Idempotency Test (Trigger Signed Webhook a 2nd time) ---")
    res_webhook2 = _post_signed_lenco_webhook(webhook_payload)
    assert res_webhook2.status_code == 200
    assert res_webhook2.json()["status"] == "noop"

    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    drink_inv_idem = (
        db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == drink_id).first()
    )
    assert (
        drink_inv_idem.stock_quantity == expected_stock
    ), "Idempotency failed: Stock decremented twice!"
    db.close()
    print("Idempotency check OK: Stock NOT decremented on duplicate webhook.")

    print("\n--- 7. Owner Dashboard Summary (RBAC + Analytics) ---")
    res_forbidden = client.get(
        "/api/dashboard/summary", headers={"Authorization": f"Bearer {cashier_token}"}
    )
    assert res_forbidden.status_code == 403
    print("RBAC check OK: Cashier forbidden from dashboard summary (HTTP 403).")

    res_summary = client.get(
        "/api/dashboard/summary", headers={"Authorization": f"Bearer {owner_token}"}
    )
    assert res_summary.status_code == 200
    summary = res_summary.json()
    print("Owner Dashboard Summary:", summary)
    assert summary["today_total_revenue_zmw"] == expected_total
    assert summary["settlement_account_balance_zmw"] == expected_total
    assert summary["today_cash_revenue_zmw"] == 0.0
    assert summary["today_orders_count"] == 1
    print("Summary metrics accurately reflect mobile money order!")

    print("\n--- 8. Owner Calendar Analytics ---")
    res_cal = client.get(
        "/api/dashboard/calendar", headers={"Authorization": f"Bearer {owner_token}"}
    )
    assert res_cal.status_code == 200
    cal_data = res_cal.json()
    print("Calendar Data:", cal_data)
    assert len(cal_data) == 1
    today_cal = cal_data[0]
    assert today_cal["total_revenue_zmw"] == expected_total
    assert today_cal["total_orders_count"] == 1
    assert today_cal["total_meals_sold"] == 2
    print(
        f"Calendar check OK: Total Meals Sold = {today_cal['total_meals_sold']}, Revenue = {today_cal['total_revenue_zmw']}"
    )

    print("\n--- 9. Add Cash Order and Verify Combined Analytics ---")
    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    meal2 = db.query(MenuItem).filter(MenuItem.name.like("%T-Bone%")).first()
    meal2_id = meal2.id
    meal2_price_zmw = ngwee_to_zmw(meal2.price_ngwee)
    db.close()

    order_cash = client.post(
        "/api/orders",
        json={
            "payment_method": "cash",
            "items": [{"menu_item_id": meal2_id, "quantity": 1}],
        },
        headers={"Authorization": f"Bearer {cashier_token}"},
    )
    assert order_cash.status_code == 201

    res_summary2 = client.get(
        "/api/dashboard/summary", headers={"Authorization": f"Bearer {owner_token}"}
    )
    summary2 = res_summary2.json()
    print("Updated Summary after Cash Order:", summary2)
    assert summary2["today_cash_revenue_zmw"] == meal2_price_zmw
    assert summary2["settlement_account_balance_zmw"] == expected_total
    assert summary2["today_orders_count"] == 2
    assert summary2["today_total_revenue_zmw"] == round(
        expected_total + meal2_price_zmw, 2
    )

    res_cal2 = client.get(
        "/api/dashboard/calendar", headers={"Authorization": f"Bearer {owner_token}"}
    )
    cal2 = res_cal2.json()[0]
    assert cal2["total_orders_count"] == 2
    assert cal2["total_meals_sold"] == 3
    print(
        f"Combined Calendar OK: Meals Sold = {cal2['total_meals_sold']}, Total Orders = {cal2['total_orders_count']}"
    )

    print("\nALL LENCO MOBILE MONEY & OWNER ANALYTICS TESTS PASSED!")


def test_lusaka_timezone_boundary_23_30():
    """Verify an order placed at 23:30 Africa/Lusaka time (21:30 UTC) counts toward that Lusaka day's totals."""
    seed()
    reset_login_rate_limiter()

    res_owner = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "aunts-lusaka",
            "username": "aunt",
            "password": "owner123",
        },
    )
    owner_token = res_owner.json()["access_token"]
    owner_id = res_owner.json()["id"]

    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    meal = db.query(MenuItem).filter(MenuItem.category == "meal").first()

    today_lusaka = datetime.now(LUSAKA_TZ).date()
    lusaka_23_30 = datetime(
        today_lusaka.year,
        today_lusaka.month,
        today_lusaka.day,
        23,
        30,
        0,
        tzinfo=LUSAKA_TZ,
    )
    utc_21_30 = lusaka_23_30.astimezone(timezone.utc)

    lusaka_00_30 = datetime(
        today_lusaka.year,
        today_lusaka.month,
        today_lusaka.day,
        0,
        30,
        0,
        tzinfo=LUSAKA_TZ,
    )
    utc_prev_day_22_30 = lusaka_00_30.astimezone(timezone.utc)

    order_late = Order(
        tenant_id=TENANT_A_ID,
        cashier_id=owner_id,
        total_ngwee=meal.price_ngwee,
        payment_method="cash",
        payment_status="paid",
        created_at=utc_21_30,
    )
    order_late.items = [
        OrderItem(
            tenant_id=TENANT_A_ID,
            menu_item_id=meal.id,
            quantity=1,
            price_at_sale_ngwee=meal.price_ngwee,
        )
    ]

    order_early = Order(
        tenant_id=TENANT_A_ID,
        cashier_id=owner_id,
        total_ngwee=meal.price_ngwee * 2,
        payment_method="cash",
        payment_status="paid",
        created_at=utc_prev_day_22_30,
    )
    order_early.items = [
        OrderItem(
            tenant_id=TENANT_A_ID,
            menu_item_id=meal.id,
            quantity=2,
            price_at_sale_ngwee=meal.price_ngwee,
        )
    ]

    db.add_all([order_late, order_early])
    db.commit()
    expected_zmw = ngwee_to_zmw(meal.price_ngwee * 3)
    db.close()

    res_summary = client.get(
        "/api/dashboard/summary", headers={"Authorization": f"Bearer {owner_token}"}
    )
    assert res_summary.status_code == 200
    summary = res_summary.json()
    assert summary["today_orders_count"] == 2
    assert summary["today_total_revenue_zmw"] == expected_zmw

    res_cal = client.get(
        f"/api/dashboard/calendar?year={today_lusaka.year}&month={today_lusaka.month}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_cal.status_code == 200
    cal_days = res_cal.json()
    assert len(cal_days) == 1
    assert cal_days[0]["date"] == today_lusaka.strftime("%Y-%m-%d")
    assert cal_days[0]["total_orders_count"] == 2
    assert cal_days[0]["total_meals_sold"] == 3
    assert cal_days[0]["total_revenue_zmw"] == expected_zmw


def test_money_conversion_helper():
    assert zmw_to_ngwee(95.0) == 9500
    assert zmw_to_ngwee("18.50") == 1850
    assert ngwee_to_zmw(9500) == 95.0
    assert ngwee_to_zmw(1855) == 18.55


def test_webhook_signature_amount_mismatch_unknown_ref_and_events():
    """
    Verify:
    - Missing or bad signature returns 401 and processes nothing
    - Amount mismatch when re-fetched from Lenco is rejected (400) and order stays pending
    - Unknown reference logs and returns 200 (no retry storm)
    - Non-collection events return 200 (ignored)
    """
    seed()
    reset_login_rate_limiter()
    mock_lenco_client.reset()

    res_cashier = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "aunts-lusaka",
            "username": "cashier1",
            "password": "cashier123",
        },
    )
    headers = {"Authorization": f"Bearer {res_cashier.json()['access_token']}"}
    menu = client.get("/api/menu", headers=headers).json()
    drink_item = next(i for i in menu if i["category"] == "drink")
    initial_stock = drink_item["drink_inventory"]["stock_quantity"]

    res_order = client.post(
        "/api/orders",
        json={
            "payment_method": "mobile_money",
            "items": [{"menu_item_id": drink_item["id"], "quantity": 2}],
        },
        headers=headers,
    )
    order_id = res_order.json()["id"]

    res_init = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "0977123456", "operator": "mtn"},
        headers=headers,
    )
    ref = res_init.json()["lenco_reference"]

    valid_payload = {
        "event": "collection.successful",
        "data": {"reference": ref, "status": "successful"},
    }

    # 1. Missing X-Lenco-Signature -> 401
    res_no_sig = client.post("/api/webhooks/lenco", json=valid_payload)
    assert res_no_sig.status_code == 401

    # 2. Invalid X-Lenco-Signature -> 401
    res_bad_sig = _post_signed_lenco_webhook(
        valid_payload, signature_override="deadbeef" * 16
    )
    assert res_bad_sig.status_code == 401

    # Verify order is still pending and stock untouched
    status_after_bad = client.get(f"/api/payments/status/{ref}", headers=headers).json()
    assert status_after_bad["payment_status"] == "pending"

    # 3. Amount mismatch at provider -> 400 and order remains pending
    mock_lenco_client.set_collection_state(
        ref, status="successful", amount_ngwee=100  # Wrong amount (1.00 ZMW)
    )
    res_mismatch = _post_signed_lenco_webhook(valid_payload)
    assert res_mismatch.status_code == 400
    status_after_mismatch = client.get(
        f"/api/payments/status/{ref}", headers=headers
    ).json()
    assert status_after_mismatch["payment_status"] == "pending"

    # 4. Unknown reference -> 200 OK (ignored, no retries storm)
    res_unknown = _post_signed_lenco_webhook(
        {
            "event": "collection.successful",
            "data": {"reference": str(uuid.uuid4()), "status": "successful"},
        }
    )
    assert res_unknown.status_code == 200
    assert res_unknown.json()["status"] == "ignored"

    # 5. Unhandled event type -> 200 OK (ignored)
    res_other_event = _post_signed_lenco_webhook(
        {
            "event": "transfer.successful",
            "data": {"reference": ref},
        }
    )
    assert res_other_event.status_code == 200
    assert res_other_event.json()["status"] == "ignored"

    # Verify stock is still untouched after all rejected/ignored webhooks
    inv_now = client.get("/api/inventory/drinks", headers=headers).json()
    drink_row = next(r for r in inv_now if r["menu_item_id"] == drink_item["id"])
    assert drink_row["stock_quantity"] == initial_stock


def test_stuck_pending_orders_reconciliation():
    """
    Verify reconciliation settles orders stuck in pending > 10 minutes by querying Lenco
    and leaves orders < 10 minutes old untouched.
    """
    seed()
    reset_login_rate_limiter()
    mock_lenco_client.reset()

    res_owner = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "aunts-lusaka",
            "username": "aunt",
            "password": "owner123",
        },
    )
    owner_headers = {"Authorization": f"Bearer {res_owner.json()['access_token']}"}
    menu = client.get("/api/menu", headers=owner_headers).json()
    drink_item = next(i for i in menu if i["category"] == "drink")
    initial_stock = drink_item["drink_inventory"]["stock_quantity"]

    # Create two pending mobile money orders: one old (15 mins ago) and one recent (2 mins ago)
    r1 = client.post(
        "/api/orders",
        json={
            "payment_method": "mobile_money",
            "items": [{"menu_item_id": drink_item["id"], "quantity": 2}],
        },
        headers=owner_headers,
    )
    old_order_id = r1.json()["id"]
    init1 = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": old_order_id, "phone": "0977123456", "operator": "airtel"},
        headers=owner_headers,
    )
    old_ref = init1.json()["lenco_reference"]

    r2 = client.post(
        "/api/orders",
        json={
            "payment_method": "mobile_money",
            "items": [{"menu_item_id": drink_item["id"], "quantity": 1}],
        },
        headers=owner_headers,
    )
    recent_order_id = r2.json()["id"]
    init2 = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": recent_order_id, "phone": "0977123456", "operator": "airtel"},
        headers=owner_headers,
    )
    recent_ref = init2.json()["lenco_reference"]

    # Backdate old_order_id to 15 minutes ago
    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    old_order = db.query(Order).filter(Order.id == old_order_id).first()
    old_order.created_at = datetime.now(timezone.utc) - timedelta(minutes=15)
    db.commit()
    db.close()

    # Simulate both collections succeeding at Lenco, but webhooks were missed
    mock_lenco_client.set_collection_state(old_ref, status="successful")
    mock_lenco_client.set_collection_state(recent_ref, status="successful")

    # Run reconciliation endpoint
    res_rec = client.post("/api/payments/reconcile", headers=owner_headers)
    assert res_rec.status_code == 200
    rec_data = res_rec.json()
    assert rec_data["checked_count"] == 1
    assert rec_data["settled_paid_count"] == 1

    # Old order (> 10 min) is now paid and stock decremented by 2
    st_old = client.get(
        f"/api/payments/status/{old_ref}", headers=owner_headers
    ).json()
    assert st_old["payment_status"] == "paid"

    # Recent order (< 10 min) is still pending
    st_recent = client.get(
        f"/api/payments/status/{recent_ref}", headers=owner_headers
    ).json()
    assert st_recent["payment_status"] == "pending"

    inv_after = client.get("/api/inventory/drinks", headers=owner_headers).json()
    drink_row = next(r for r in inv_after if r["menu_item_id"] == drink_item["id"])
    assert drink_row["stock_quantity"] == initial_stock - 2

    # Also verify the multi-tenant job helper is idempotent on a second run
    all_res = reconcile_all_tenants_stuck_orders(older_than_minutes=10)
    assert all_res["aunts-lusaka"].settled_paid_count == 0


def test_live_lenco_client_httpx_and_log_redaction(caplog, monkeypatch):
    """Verify LiveLencoClient httpx calls and ensure neither LENCO_API_TOKEN nor full phone numbers are logged."""
    secret_token = "super-secret-live-lenco-token-99999"
    full_phone = "260977123456"
    ref = str(uuid.uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {secret_token}"
        if request.method == "POST" and request.url.path.endswith("/collections/mobile-money"):
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "message": "Collection initiated",
                    "data": {
                        "reference": ref,
                        "lencoReference": "LENCO-LIVE-001",
                        "amount": "50.00",
                        "currency": "ZMW",
                        "status": "pay-offline",
                    },
                },
            )
        if request.method == "GET" and request.url.path.endswith(f"/collections/status/{ref}"):
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "message": "Collection retrieved",
                    "data": {
                        "reference": ref,
                        "lencoReference": "LENCO-LIVE-001",
                        "amount": "50.00",
                        "currency": "ZMW",
                        "status": "successful",
                    },
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    orig_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *args, **kwargs: orig_client(*args, transport=transport, **kwargs),
    )

    live_client = LiveLencoClient(
        api_token=secret_token, base_url="https://api.lenco.co/access/v2"
    )
    with caplog.at_level(logging.INFO, logger="bomapos.lenco"):
        res_collect = live_client.collect_mobile_money(
            reference=ref,
            phone=full_phone,
            operator="airtel",
            amount_ngwee=5000,
            currency="ZMW",
        )
        assert res_collect.status == "pending"
        assert res_collect.amount_ngwee == 5000

        res_status = live_client.get_collection_by_reference(ref)
        assert res_status is not None
        assert res_status.status == "successful"
        assert res_status.amount_ngwee == 5000

    log_text = caplog.text
    assert secret_token not in log_text, "LENCO_API_TOKEN leaked into logs!"
    assert full_phone not in log_text, "Full customer phone number leaked into logs!"
    assert "***456" in log_text


if __name__ == "__main__":
    test_payments_and_analytics_workflow()
    test_lusaka_timezone_boundary_23_30()
    test_money_conversion_helper()
