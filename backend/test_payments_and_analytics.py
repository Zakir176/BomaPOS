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
os.environ["CRON_SECRET"] = "test-cron-secret-key-12345"

import httpx
from fastapi.testclient import TestClient
from main import (
    app,
    reset_login_rate_limiter,
    reconcile_all_tenants_stuck_orders,
    validate_cron_secret,
    validate_startup_config,
)
from database import SessionLocal, bind_session_to_tenant
from lenco_client import (
    LiveLencoClient,
    compute_lenco_webhook_signature,
    mock_lenco_client,
    format_zambian_phone,
)
from models import DrinkInventory, MenuItem, Order, OrderItem, PaymentAttempt
from money import ngwee_to_zmw, zmw_to_ngwee
from seed import seed, TENANT_A_ID, TENANT_B_ID
import pytest

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

    # Backdate old_order_id and its attempt to 15 minutes ago
    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    old_order = db.query(Order).filter(Order.id == old_order_id).first()
    old_order.created_at = datetime.now(timezone.utc) - timedelta(minutes=15)
    old_att = db.query(PaymentAttempt).filter(PaymentAttempt.order_id == old_order_id).first()
    if old_att:
        old_att.created_at = datetime.now(timezone.utc) - timedelta(minutes=15)
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
                        "id": "col-live-001",
                        "reference": ref,
                        "lencoReference": "LENCO-LIVE-001",
                        "amount": "50.00",
                        "fee": "1.00",
                        "bearer": "merchant",
                        "settlementStatus": "pending",
                        "currency": "ZMW",
                        "status": "pay-offline",
                    },
                },
            )
        if request.method == "POST" and request.url.path.endswith("/collections/mobile-money/submit-otp"):
            body = json.loads(request.content.decode("utf-8"))
            assert body["otp"] == "123456"
            assert body["id"] == "col-live-001"
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "message": "OTP verified",
                    "data": {
                        "id": "col-live-001",
                        "reference": ref,
                        "lencoReference": "LENCO-LIVE-001",
                        "amount": "50.00",
                        "fee": "1.00",
                        "bearer": "merchant",
                        "settlementStatus": "pending",
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
                        "id": "col-live-001",
                        "reference": ref,
                        "lencoReference": "LENCO-LIVE-001",
                        "amount": "50.00",
                        "fee": "1.00",
                        "bearer": "merchant",
                        "settlementStatus": "settled",
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
        assert res_collect.status == "pay-offline"
        assert res_collect.amount_ngwee == 5000
        assert res_collect.fee_ngwee == 100
        assert res_collect.fee_bearer == "merchant"
        assert res_collect.settlement_status == "pending"

        res_otp = live_client.submit_mobile_money_otp(
            reference=ref,
            otp="123456",
            collection_id="col-live-001",
        )
        assert res_otp.status == "pay-offline"

        res_status = live_client.get_collection_by_reference(ref)
        assert res_status is not None
        assert res_status.status == "successful"
        assert res_status.amount_ngwee == 5000
        assert res_status.fee_ngwee == 100
        assert res_status.settlement_status == "settled"

    log_text = caplog.text
    assert secret_token not in log_text, "LENCO_API_TOKEN leaked into logs!"
    assert full_phone not in log_text, "Full customer phone number leaked into logs!"
    assert "***456" in log_text


def test_stock_out_between_order_creation_and_settlement_marks_paid_and_needs_review():
    """
    Requirement 2 & 7:
    Stock-out between order creation and payment settlement must never fail settlement:
    always mark the order paid, clamp drink stock at zero, and set orders.needs_review=True
    with a short reason (and surface it in order and dashboard responses).
    Cash orders keep rejecting insufficient stock at creation with HTTP 400.
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
    drink_inv_id = drink_item["drink_inventory"]["id"]

    # Set stock to 3 units
    res_patch = client.patch(
        f"/api/inventory/drinks/{drink_inv_id}",
        json={"stock_quantity": 3},
        headers=owner_headers,
    )
    assert res_patch.status_code == 200

    # 1. Create a pending mobile money order for 3 drinks (stock is 3 at creation -> allowed)
    res_momo = client.post(
        "/api/orders",
        json={
            "payment_method": "mobile_money",
            "items": [{"menu_item_id": drink_item["id"], "quantity": 3}],
        },
        headers=owner_headers,
    )
    assert res_momo.status_code == 201
    momo_order_id = res_momo.json()["id"]
    assert res_momo.json()["needs_review"] is False

    res_init = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": momo_order_id, "phone": "0977123456", "operator": "airtel"},
        headers=owner_headers,
    )
    assert res_init.status_code == 200
    ref = res_init.json()["lenco_reference"]

    # 2. Before the mobile money payment settles, a cash order buys 2 of the 3 drinks (leaving 1 in stock)
    res_cash = client.post(
        "/api/orders",
        json={
            "payment_method": "cash",
            "items": [{"menu_item_id": drink_item["id"], "quantity": 2}],
        },
        headers=owner_headers,
    )
    assert res_cash.status_code == 201

    # Cash orders still reject insufficient stock at creation (requesting 5 when 1 left -> 400)
    res_cash_fail = client.post(
        "/api/orders",
        json={
            "payment_method": "cash",
            "items": [{"menu_item_id": drink_item["id"], "quantity": 5}],
        },
        headers=owner_headers,
    )
    assert res_cash_fail.status_code == 400

    # 3. Now verified successful payment arrives for the mobile money order (needs 3, only 1 in stock)
    mock_lenco_client.set_collection_state(ref, status="successful")
    res_wh = _post_signed_lenco_webhook(
        {
            "event": "collection.successful",
            "data": {"reference": ref, "status": "successful"},
        }
    )
    assert res_wh.status_code == 200
    assert res_wh.json()["status"] == "success"
    assert res_wh.json()["needs_review"] is True

    # Verify payment status endpoint shows paid + needs_review=True + review_reason
    st = client.get(f"/api/payments/status/{ref}", headers=owner_headers).json()
    assert st["payment_status"] == "paid"
    assert st["needs_review"] is True
    assert drink_item["name"] in (st["review_reason"] or "")

    # Verify stock is clamped at 0 (not negative)
    inv_after = client.get("/api/inventory/drinks", headers=owner_headers).json()
    drink_row = next(r for r in inv_after if r["menu_item_id"] == drink_item["id"])
    assert drink_row["stock_quantity"] == 0

    # Verify dashboard summary surfaces needs_review_count and needs_review_orders
    dash = client.get("/api/dashboard/summary", headers=owner_headers).json()
    assert dash["needs_review_count"] == 1
    assert len(dash["needs_review_orders"]) == 1
    assert dash["needs_review_orders"][0]["id"] == momo_order_id
    assert dash["needs_review_orders"][0]["needs_review"] is True
    assert drink_item["name"] in dash["needs_review_orders"][0]["review_reason"]


def test_payment_attempts_blocking_retry_and_late_first_attempt_settlement():
    """
    Requirement 1, 4 & 7:
    - Active attempt blocks creating a second attempt (HTTP 409) until the first attempt fails/expires at Lenco.
    - Retry after first attempt fails creates a second PaymentAttempt without overwriting the first.
    - Late payment webhook on the FIRST attempt still resolves and settles the order, recording fee, bearer,
      and settlementStatus on the attempt.
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
    headers = {"Authorization": f"Bearer {res_owner.json()['access_token']}"}
    menu = client.get("/api/menu", headers=headers).json()
    meal_item = next(i for i in menu if i["category"] == "meal")

    res_order = client.post(
        "/api/orders",
        json={
            "payment_method": "mobile_money",
            "items": [{"menu_item_id": meal_item["id"], "quantity": 1}],
        },
        headers=headers,
    )
    order_id = res_order.json()["id"]

    # 1. Initiate first attempt
    init1 = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "0977123456", "operator": "airtel"},
        headers=headers,
    )
    assert init1.status_code == 200
    ref1 = init1.json()["lenco_reference"]
    assert init1.json()["status"] == "pay-offline"

    # 2. While first attempt is still active at Lenco ('pay-offline'), initiating a second attempt is blocked
    init_blocked = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "0966123456", "operator": "mtn"},
        headers=headers,
    )
    assert init_blocked.status_code == 409

    # 3. First attempt fails at Lenco -> now a second attempt is allowed and creates a NEW row
    mock_lenco_client.set_collection_state(ref1, status="failed")
    init2 = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "0966123456", "operator": "mtn"},
        headers=headers,
    )
    assert init2.status_code == 200
    ref2 = init2.json()["lenco_reference"]
    assert ref2 != ref1

    # Verify both PaymentAttempt rows exist in DB
    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    attempts = (
        db.query(PaymentAttempt)
        .filter(PaymentAttempt.order_id == order_id)
        .order_by(PaymentAttempt.id.asc())
        .all()
    )
    assert len(attempts) == 2
    assert attempts[0].reference == ref1
    assert attempts[0].status == "failed"
    assert attempts[1].reference == ref2
    assert attempts[1].status == "pay-offline"
    db.close()

    # 4. Now a late successful payment arrives for the FIRST attempt (ref1)!
    mock_lenco_client.set_collection_state(
        ref1,
        status="successful",
        fee_ngwee=190,
        fee_bearer="merchant",
        settlement_status="settled",
        lenco_reference="LENCO-LATE-001",
    )
    res_late_wh = _post_signed_lenco_webhook(
        {
            "event": "collection.successful",
            "data": {"reference": ref1, "status": "successful"},
        }
    )
    assert res_late_wh.status_code == 200
    assert res_late_wh.json()["status"] == "success"

    # Verify the order is settled to paid and attempt 1 recorded fee, bearer, and settlement_status
    st1 = client.get(f"/api/payments/status/{ref1}", headers=headers).json()
    assert st1["payment_status"] == "paid"

    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    a1 = db.query(PaymentAttempt).filter(PaymentAttempt.reference == ref1).first()
    assert a1.status == "successful"
    assert a1.fee_ngwee == 190
    assert a1.fee_bearer == "merchant"
    assert a1.settlement_status == "settled"
    assert a1.lenco_reference == "LENCO-LATE-001"
    db.close()


def test_otp_happy_path_with_mock():
    """
    Requirement 3 & 7:
    OTP happy path with the mock:
    - Initiate returns status='otp-required'
    - POST /api/payments/mobile-money/submit-otp transitions to 'pay-offline' (or 'successful')
    - Subsequent webhook / status poll completes payment to 'paid'.
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
    meal_item = next(i for i in menu if i["category"] == "meal")

    res_order = client.post(
        "/api/orders",
        json={
            "payment_method": "mobile_money",
            "items": [{"menu_item_id": meal_item["id"], "quantity": 1}],
        },
        headers=headers,
    )
    order_id = res_order.json()["id"]

    # Configure mock to require OTP on initiate
    mock_lenco_client.set_next_initial_status("otp-required")
    res_init = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "0977120000", "operator": "airtel"},
        headers=headers,
    )
    assert res_init.status_code == 200
    assert res_init.json()["status"] == "otp-required"
    ref = res_init.json()["lenco_reference"]

    # Polling status before OTP shows distinct status 'otp-required'
    st_otp = client.get(f"/api/payments/status/{ref}", headers=headers).json()
    assert st_otp["payment_status"] == "pending"
    assert st_otp["status"] == "otp-required"

    # Submit OTP via POST /api/payments/mobile-money/submit-otp
    res_otp = client.post(
        "/api/payments/mobile-money/submit-otp",
        json={"order_id": order_id, "otp": "123456"},
        headers=headers,
    )
    assert res_otp.status_code == 200
    assert res_otp.json()["status"] == "pay-offline"

    st_offline = client.get(f"/api/payments/status/{ref}", headers=headers).json()
    assert st_offline["status"] == "pay-offline"

    # Complete approval on phone via webhook
    mock_lenco_client.set_collection_state(ref, status="successful")
    res_wh = _post_signed_lenco_webhook(
        {
            "event": "collection.successful",
            "data": {"reference": ref, "status": "successful"},
        }
    )
    assert res_wh.status_code == 200

    st_final = client.get(f"/api/payments/status/{ref}", headers=headers).json()
    assert st_final["payment_status"] == "paid"
    assert st_final["status"] == "successful"


def test_expiry_after_30_minutes_and_late_webhook_settles_expired_order(monkeypatch):
    """
    Requirement 5, 6 & 7:
    - Orders pending > 30 minutes and confirmed not-successful at Lenco become status='expired'.
    - Late webhooks still settle expired orders to 'paid'.
    - POST /internal/reconcile requires X-Cron-Secret header.
    """
    seed()
    reset_login_rate_limiter()
    mock_lenco_client.reset()
    monkeypatch.setenv("CRON_SECRET", "test-cron-secret-key-12345")

    # Verify validate_cron_secret fails startup when LENCO_MODE=live and CRON_SECRET is empty
    with pytest.raises(RuntimeError):
        validate_cron_secret(lenco_mode="live", cron_secret="")

    res_owner = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "aunts-lusaka",
            "username": "aunt",
            "password": "owner123",
        },
    )
    headers = {"Authorization": f"Bearer {res_owner.json()['access_token']}"}
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
        json={"order_id": order_id, "phone": "0977123456", "operator": "airtel"},
        headers=headers,
    )
    ref = res_init.json()["lenco_reference"]

    # Backdate order and attempt to 35 minutes ago (> 30 minutes)
    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    past_35m = datetime.now(timezone.utc) - timedelta(minutes=35)
    order_row = db.query(Order).filter(Order.id == order_id).first()
    order_row.created_at = past_35m
    attempt_row = (
        db.query(PaymentAttempt).filter(PaymentAttempt.reference == ref).first()
    )
    attempt_row.created_at = past_35m
    db.commit()
    db.close()

    # 1. Verify /internal/reconcile rejects missing or wrong X-Cron-Secret
    res_no_secret = client.post("/internal/reconcile")
    assert res_no_secret.status_code == 401

    res_bad_secret = client.post(
        "/internal/reconcile", headers={"X-Cron-Secret": "wrong-secret"}
    )
    assert res_bad_secret.status_code == 401

    # 2. Call /internal/reconcile with valid X-Cron-Secret while collection is still 'pay-offline' at Lenco
    res_cron = client.post(
        "/internal/reconcile",
        headers={"X-Cron-Secret": "test-cron-secret-key-12345"},
    )
    assert res_cron.status_code == 200
    tenant_rec = res_cron.json()["aunts-lusaka"]
    assert tenant_rec["checked_count"] == 1
    assert tenant_rec["expired_count"] == 1

    # Verify both order and attempt are now 'expired'
    st_exp = client.get(f"/api/payments/status/{ref}", headers=headers).json()
    assert st_exp["payment_status"] == "expired"
    assert st_exp["status"] == "expired"

    # 3. Late webhook arrives for the expired order -> must still settle the order to 'paid' and deduct stock!
    mock_lenco_client.set_collection_state(ref, status="successful")
    res_late_wh = _post_signed_lenco_webhook(
        {
            "event": "collection.successful",
            "data": {"reference": ref, "status": "successful"},
        }
    )
    assert res_late_wh.status_code == 200
    assert res_late_wh.json()["status"] == "success"

    st_settled = client.get(f"/api/payments/status/{ref}", headers=headers).json()
    assert st_settled["payment_status"] == "paid"
    assert st_settled["status"] == "successful"

    inv_now = client.get("/api/inventory/drinks", headers=headers).json()
    drink_row = next(r for r in inv_now if r["menu_item_id"] == drink_item["id"])
    assert drink_row["stock_quantity"] == initial_stock - 2


def test_zambian_phone_formatting():
    from fastapi import HTTPException

    # Local mode (default)
    assert format_zambian_phone("0977123456", format_type="local") == "0977123456"
    assert format_zambian_phone("+260977123456", format_type="local") == "0977123456"
    assert format_zambian_phone("260977123456", format_type="local") == "0977123456"
    assert format_zambian_phone("096-123-4567", format_type="local") == "0961234567"
    assert format_zambian_phone("095 123 4567", format_type="local") == "0951234567"
    assert format_zambian_phone("0771234567", format_type="local") == "0771234567"
    assert format_zambian_phone("0761234567", format_type="local") == "0761234567"
    assert format_zambian_phone("0751234567", format_type="local") == "0751234567"

    # International mode
    assert format_zambian_phone("0977123456", format_type="international") == "260977123456"
    assert format_zambian_phone("+260961234567", format_type="international") == "260961234567"

    # Invalid numbers
    for invalid in ["123456", "0981234567", "0941234567", "", "+123456789012"]:
        with pytest.raises(HTTPException) as exc_info:
            format_zambian_phone(invalid)
        assert exc_info.value.status_code == 400


def test_startup_validation_live_mode():
    # In live mode, both LENCO_API_TOKEN and CRON_SECRET are required
    with pytest.raises(RuntimeError, match="LENCO_API_TOKEN"):
        validate_startup_config("live", lenco_api_token="", cron_secret="secret123")

    with pytest.raises(RuntimeError, match="CRON_SECRET"):
        validate_startup_config("live", lenco_api_token="token123", cron_secret="")

    # Should succeed when both are provided
    validate_startup_config("live", lenco_api_token="token123", cron_secret="secret123")

    # In mock mode, missing tokens should not raise
    validate_startup_config("mock", lenco_api_token="", cron_secret="")


def test_write_ahead_attempt_and_timeout():
    seed()
    res_cashier = client.post(
        "/api/auth/login",
        json={"tenant_slug": "aunts-lusaka", "username": "cashier1", "password": "cashier123"},
    )
    headers = {"Authorization": f"Bearer {res_cashier.json()['access_token']}"}

    res_menu = client.get("/api/menu", headers=headers).json()
    item = res_menu[0]

    # Create order
    res_order = client.post(
        "/api/orders",
        json={"payment_method": "mobile_money", "items": [{"menu_item_id": item["id"], "quantity": 1}]},
        headers=headers,
    )
    order_id = res_order.json()["id"]

    # Simulate Lenco timeout or exception during collect_mobile_money
    orig_collect = mock_lenco_client.collect_mobile_money

    def timeout_collect(**kwargs):
        raise httpx.ConnectTimeout("Connection timed out to Lenco gateway")

    mock_lenco_client.collect_mobile_money = timeout_collect

    try:
        res_init = client.post(
            "/api/payments/mobile-money/initiate",
            json={"order_id": order_id, "phone": "0977123456", "operator": "airtel"},
            headers=headers,
        )
        assert res_init.status_code == 502
        assert "Payment provider timed out or returned an error" in res_init.json()["detail"]
    finally:
        mock_lenco_client.collect_mobile_money = orig_collect

    # Check that attempt was committed with status 'initiating' (write-ahead commit)
    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    attempt = db.query(PaymentAttempt).filter(PaymentAttempt.order_id == order_id).first()
    assert attempt is not None
    assert attempt.status == "initiating"

    # Immediately trying to initiate again returns 409 Conflict
    res_retry = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "0977123456", "operator": "airtel"},
        headers=headers,
    )
    assert res_retry.status_code == 409
    assert "already in progress" in res_retry.json()["detail"]

    # Reconciliation handles 'initiating' attempt older than 2 minutes:
    # If Lenco has no record (mock returns None), marks attempt 'failed' and order 'failed'
    attempt.created_at = datetime.now(timezone.utc) - timedelta(minutes=3)
    attempt_ref = attempt.reference
    db.commit()
    db.close()

    res_rec = client.post("/internal/reconcile", headers={"X-Cron-Secret": "test-cron-secret-key-12345"})
    assert res_rec.status_code == 200
    assert res_rec.json()["aunts-lusaka"]["settled_failed_count"] >= 1

    # Status check confirms failed
    res_st = client.get(f"/api/payments/status/{attempt_ref}", headers=headers).json()
    assert res_st["payment_status"] == "failed"
    assert res_st["status"] == "failed"


def test_order_age_vs_attempt_age_expiry():
    seed()
    res_cashier = client.post(
        "/api/auth/login",
        json={"tenant_slug": "aunts-lusaka", "username": "cashier1", "password": "cashier123"},
    )
    headers = {"Authorization": f"Bearer {res_cashier.json()['access_token']}"}

    res_menu = client.get("/api/menu", headers=headers).json()
    item = res_menu[0]

    # Create order
    res_order = client.post(
        "/api/orders",
        json={"payment_method": "mobile_money", "items": [{"menu_item_id": item["id"], "quantity": 1}]},
        headers=headers,
    )
    order_id = res_order.json()["id"]

    # Initiate attempt (attempt is fresh, e.g. now)
    res_init = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "0977123456", "operator": "airtel"},
        headers=headers,
    )
    assert res_init.status_code == 200
    ref = res_init.json()["lenco_reference"]

    # Backdate ORDER to 45 minutes ago (> 30 min expiry), but keep ATTEMPT fresh (5 minutes ago)
    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    order_row = db.query(Order).filter(Order.id == order_id).first()
    order_row.created_at = datetime.now(timezone.utc) - timedelta(minutes=45)
    attempt_row = db.query(PaymentAttempt).filter(PaymentAttempt.reference == ref).first()
    attempt_row.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()
    db.close()

    # Second initiate must NOT expire the fresh attempt and must return 409 Conflict
    res_second = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "0977123456", "operator": "airtel"},
        headers=headers,
    )
    assert res_second.status_code == 409
    assert "already in progress" in res_second.json()["detail"]


def test_duplicate_payment_detection_webhook_otp_reconcile():
    seed()
    res_cashier = client.post(
        "/api/auth/login",
        json={"tenant_slug": "aunts-lusaka", "username": "cashier1", "password": "cashier123"},
    )
    headers = {"Authorization": f"Bearer {res_cashier.json()['access_token']}"}

    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    drink = db.query(MenuItem).filter(MenuItem.category == "drink").first()
    drink_id = drink.id
    inv_before = db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == drink_id).first()
    initial_stock = inv_before.stock_quantity
    db.close()

    # 1. Create order for 1 drink
    res_order = client.post(
        "/api/orders",
        json={"payment_method": "mobile_money", "items": [{"menu_item_id": drink_id, "quantity": 1}]},
        headers=headers,
    )
    order_id = res_order.json()["id"]

    # Initiate attempt A
    res_init_a = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "0977123456", "operator": "airtel"},
        headers=headers,
    )
    ref_a = res_init_a.json()["lenco_reference"]

    # Settle attempt A via webhook -> order is marked paid and stock is decremented by 1
    mock_lenco_client.set_collection_state(ref_a, status="successful")
    res_wh_a = _post_signed_lenco_webhook(
        {"event": "collection.successful", "data": {"reference": ref_a, "status": "successful"}}
    )
    assert res_wh_a.status_code == 200
    assert res_wh_a.json()["status"] == "success"

    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    order_row = db.query(Order).filter(Order.id == order_id).first()
    assert order_row.payment_status == "paid"
    assert order_row.needs_review is False
    order_total_ngwee = order_row.total_ngwee
    inv = db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == drink_id).first()
    assert inv.stock_quantity == initial_stock - 1

    # 2. Duplicate payment via WEBHOOK on attempt B
    attempt_b_ref = str(uuid.uuid4())
    attempt_b = PaymentAttempt(
        tenant_id=TENANT_A_ID,
        order_id=order_id,
        reference=attempt_b_ref,
        status="pending",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    db.add(attempt_b)
    db.commit()
    db.close()

    mock_lenco_client.set_collection_state(attempt_b_ref, status="successful", amount_ngwee=order_total_ngwee)
    res_wh_b = _post_signed_lenco_webhook(
        {"event": "collection.successful", "data": {"reference": attempt_b_ref, "status": "successful"}}
    )
    assert res_wh_b.status_code == 200

    # Verify duplicate payment detected: needs_review is True, review_reason appended, stock NOT double-decremented
    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    order_row = db.query(Order).filter(Order.id == order_id).first()
    assert order_row.needs_review is True
    assert f"Duplicate payment on attempt {attempt_b_ref}: refund required" in order_row.review_reason
    inv = db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == drink_id).first()
    assert inv.stock_quantity == initial_stock - 1  # Never double decremented!

    # 3. Duplicate payment via OTP on attempt C
    attempt_c_ref = str(uuid.uuid4())
    attempt_c = PaymentAttempt(
        tenant_id=TENANT_A_ID,
        order_id=order_id,
        reference=attempt_c_ref,
        status="otp-required",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=2),
    )
    db.add(attempt_c)
    db.commit()
    db.close()

    mock_lenco_client.set_collection_state(attempt_c_ref, status="otp-required", amount_ngwee=order_total_ngwee)
    mock_lenco_client.set_otp_next_status("successful")
    res_otp = client.post(
        "/api/payments/mobile-money/submit-otp",
        json={"order_id": order_id, "otp": "123456", "reference": attempt_c_ref},
        headers=headers,
    )
    assert res_otp.status_code == 200

    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    order_row = db.query(Order).filter(Order.id == order_id).first()
    assert f"Duplicate payment on attempt {attempt_c_ref}: refund required" in order_row.review_reason
    inv = db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == drink_id).first()
    assert inv.stock_quantity == initial_stock - 1  # Still not double decremented!

    # 4. Duplicate payment via RECONCILIATION on attempt D
    attempt_d_ref = str(uuid.uuid4())
    past_15m = datetime.now(timezone.utc) - timedelta(minutes=15)
    attempt_d = PaymentAttempt(
        tenant_id=TENANT_A_ID,
        order_id=order_id,
        reference=attempt_d_ref,
        status="pending",
        created_at=past_15m,
        updated_at=past_15m,
    )
    db.add(attempt_d)
    db.commit()
    db.close()

    mock_lenco_client.set_collection_state(attempt_d_ref, status="successful", amount_ngwee=order_total_ngwee)
    res_cron = client.post("/internal/reconcile", headers={"X-Cron-Secret": "test-cron-secret-key-12345"})
    assert res_cron.status_code == 200

    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    order_row = db.query(Order).filter(Order.id == order_id).first()
    assert f"Duplicate payment on attempt {attempt_d_ref}: refund required" in order_row.review_reason
    inv = db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == drink_id).first()
    assert inv.stock_quantity == initial_stock - 1  # Never double decremented!
    db.close()


def test_abandon_payment_attempt_and_reconciliation():
    seed()
    res_cashier = client.post(
        "/api/auth/login",
        json={"tenant_slug": "aunts-lusaka", "username": "cashier1", "password": "cashier123"},
    )
    headers = {"Authorization": f"Bearer {res_cashier.json()['access_token']}"}

    res_menu = client.get("/api/menu", headers=headers).json()
    item = res_menu[0]

    # Create order
    res_order = client.post(
        "/api/orders",
        json={"payment_method": "mobile_money", "items": [{"menu_item_id": item["id"], "quantity": 1}]},
        headers=headers,
    )
    order_id = res_order.json()["id"]

    # Initiate attempt 1
    res_init1 = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "0977123456", "operator": "airtel"},
        headers=headers,
    )
    assert res_init1.status_code == 200
    ref1 = res_init1.json()["lenco_reference"]

    # Calling initiate again immediately fails with 409
    res_fail = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "0977123456", "operator": "airtel"},
        headers=headers,
    )
    assert res_fail.status_code == 409

    # Cashier clicks "Change number / retry" -> calls abandon endpoint
    res_abandon = client.post(
        "/api/payments/mobile-money/abandon",
        json={"order_id": order_id, "reference": ref1},
        headers=headers,
    )
    assert res_abandon.status_code == 200
    assert res_abandon.json()["status"] == "abandoned"

    # Now cashier can immediately initiate attempt 2 on a new number!
    res_init2 = client.post(
        "/api/payments/mobile-money/initiate",
        json={"order_id": order_id, "phone": "0961234567", "operator": "mtn"},
        headers=headers,
    )
    assert res_init2.status_code == 200
    ref2 = res_init2.json()["lenco_reference"]
    assert ref2 != ref1

    # Reconciliation queries abandoned attempt within 60 minutes:
    # If customer actually approved attempt 1 late at Lenco, reconcile will settle it or flag duplicate!
    order_total_ngwee = zmw_to_ngwee(str(res_order.json()["total_amount"]))
    mock_lenco_client.set_collection_state(ref1, status="successful", amount_ngwee=order_total_ngwee)
    res_rec = client.post("/internal/reconcile", headers={"X-Cron-Secret": "test-cron-secret-key-12345"})
    assert res_rec.status_code == 200

    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    order_row = db.query(Order).filter(Order.id == order_id).first()
    assert order_row.payment_status == "paid"
    att1 = db.query(PaymentAttempt).filter(PaymentAttempt.reference == ref1).first()
    assert att1.status == "successful"
    db.close()


if __name__ == "__main__":
    test_payments_and_analytics_workflow()
    test_lusaka_timezone_boundary_23_30()
    test_money_conversion_helper()
