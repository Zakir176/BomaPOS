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

from fastapi.testclient import TestClient
from main import app, reset_login_rate_limiter
from database import SessionLocal, bind_session_to_tenant
from models import DrinkInventory, MenuItem
from money import ngwee_to_zmw
from seed import seed, TENANT_A_ID

client = TestClient(app)


def test_core_api_workflow():
    seed()
    reset_login_rate_limiter()

    print("--- 1. Testing Login ---")
    res_cashier = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "aunts-lusaka",
            "username": "cashier1",
            "password": "cashier123",
        },
    )
    assert res_cashier.status_code == 200, f"Cashier login failed: {res_cashier.text}"
    cashier_data = res_cashier.json()
    print("Cashier login OK:", cashier_data["username"], cashier_data["role"])
    cashier_token = cashier_data["access_token"]
    cashier_id = cashier_data["id"]

    res_owner = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "aunts-lusaka",
            "username": "aunt",
            "password": "owner123",
        },
    )
    assert res_owner.status_code == 200, f"Owner login failed: {res_owner.text}"
    owner_data = res_owner.json()
    print("Owner login OK:", owner_data["username"], owner_data["role"])
    owner_token = owner_data["access_token"]

    print("\n--- 2. Testing Menu Retrieval ---")
    res_menu = client.get(
        "/api/menu", headers={"Authorization": f"Bearer {cashier_token}"}
    )
    assert res_menu.status_code == 200, f"Get menu failed: {res_menu.text}"
    menu = res_menu.json()
    print(f"Retrieved {len(menu)} menu items.")
    assert len(menu) == 10, f"Expected 10 items for Tenant A, got {len(menu)}"
    drinks = [m for m in menu if m["category"] == "drink"]
    assert len(drinks) == 5, "Expected 5 drinks for Tenant A"
    first_drink = drinks[0]
    assert "price_zmw" in first_drink
    print(
        f"Sample Drink: {first_drink['name']} | Price ZMW: {first_drink['price_zmw']} | Stock: {first_drink['drink_inventory']['stock_quantity']}"
    )

    print("\n--- 3. Testing Drink Inventory Endpoint ---")
    res_inv = client.get(
        "/api/inventory/drinks", headers={"Authorization": f"Bearer {cashier_token}"}
    )
    assert res_inv.status_code == 200
    inv_list = res_inv.json()
    assert len(inv_list) == 5
    print(f"Retrieved {len(inv_list)} drink inventory rows.")

    print("\n--- 4. Testing Role Protection ---")
    res_forbidden = client.patch(
        f"/api/inventory/drinks/{inv_list[0]['id']}",
        json={"stock_quantity": 100},
        headers={"Authorization": f"Bearer {cashier_token}"},
    )
    assert (
        res_forbidden.status_code == 403
    ), f"Expected 403 for cashier, got {res_forbidden.status_code}"
    print("RBAC check OK: Cashier forbidden from modifying inventory (HTTP 403).")

    res_owner_update = client.patch(
        f"/api/inventory/drinks/{inv_list[0]['id']}",
        json={"stock_quantity": inv_list[0]["stock_quantity"]},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_owner_update.status_code == 200
    print("RBAC check OK: Owner successfully updated inventory.")

    print("\n--- 5. Testing Order Creation & Atomic Stock Deduction ---")
    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    mosi_item = db.query(MenuItem).filter(MenuItem.name.like("%Mosi Light%")).first()
    assert mosi_item is not None, "Mosi Light not found"
    mosi_id = mosi_item.id
    mosi_price_ngwee = mosi_item.price_ngwee
    mosi_inv = (
        db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == mosi_id).first()
    )
    initial_stock = mosi_inv.stock_quantity
    meal_item = db.query(MenuItem).filter(MenuItem.category == "meal").first()
    meal_id = meal_item.id
    meal_price_ngwee = meal_item.price_ngwee
    db.close()

    print(f"Pre-order Mosi Light Stock: {initial_stock}")

    order_payload = {
        "payment_method": "cash",
        "items": [
            {"menu_item_id": meal_id, "quantity": 1},
            {"menu_item_id": mosi_id, "quantity": 2},
        ],
    }

    res_order = client.post(
        "/api/orders",
        json=order_payload,
        headers={"Authorization": f"Bearer {cashier_token}"},
    )
    assert res_order.status_code == 201, f"Order creation failed: {res_order.text}"
    order_data = res_order.json()
    expected_total_zmw = ngwee_to_zmw(meal_price_ngwee * 1 + mosi_price_ngwee * 2)
    print(
        "Order created:",
        order_data["id"],
        "Total:",
        order_data["total_amount"],
        "Status:",
        order_data["payment_status"],
    )
    assert order_data["cashier_id"] == cashier_id
    assert order_data["total_amount"] == expected_total_zmw
    assert order_data["payment_status"] == "paid"

    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    mosi_inv_after = (
        db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == mosi_id).first()
    )
    new_stock = mosi_inv_after.stock_quantity
    db.close()

    print(f"Post-order Mosi Light Stock: {new_stock}")
    assert (
        new_stock == initial_stock - 2
    ), f"Stock should decrement by 2 (from {initial_stock} to {initial_stock - 2}), got {new_stock}"
    print("Stock deduction check OK!")

    print("\n--- 6. Testing Insufficient Stock Rejection (Atomic 0 rows affected -> 400) ---")
    excessive_order = {
        "payment_method": "cash",
        "items": [
            {"menu_item_id": mosi_id, "quantity": 9999},
        ],
    }
    res_fail = client.post(
        "/api/orders",
        json=excessive_order,
        headers={"Authorization": f"Bearer {cashier_token}"},
    )
    assert (
        res_fail.status_code == 400
    ), f"Expected 400, got {res_fail.status_code}: {res_fail.text}"
    print(f"Insufficient stock rejection check OK: {res_fail.json()['detail']}")

    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    mosi_inv_unchanged = (
        db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == mosi_id).first()
    )
    assert mosi_inv_unchanged.stock_quantity == new_stock
    db.close()

    print("\n--- 7. Testing Mobile Money Pending Status ---")
    momo_order = {
        "payment_method": "mobile_money",
        "items": [
            {"menu_item_id": mosi_id, "quantity": 1},
        ],
    }
    res_momo = client.post(
        "/api/orders",
        json=momo_order,
        headers={"Authorization": f"Bearer {cashier_token}"},
    )
    assert res_momo.status_code == 201
    momo_data = res_momo.json()
    assert momo_data["payment_status"] == "pending"
    print("Mobile money order created with status 'pending': OK!")

    db = SessionLocal()
    bind_session_to_tenant(db, TENANT_A_ID)
    mosi_inv_momo = (
        db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == mosi_id).first()
    )
    assert (
        mosi_inv_momo.stock_quantity == new_stock
    ), "Mobile money pending order should NOT deduct stock yet"
    db.close()
    print("Mobile money pending order did not deduct stock: OK!")

    print("\nALL BACKEND API VERIFICATIONS PASSED!")


if __name__ == "__main__":
    test_core_api_workflow()
