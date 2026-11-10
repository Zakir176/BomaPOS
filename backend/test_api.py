import sys
from fastapi.testclient import TestClient
from main import app
from database import SessionLocal
from models import DrinkInventory, MenuItem

client = TestClient(app)

print("--- 1. Testing Login ---")
# Cashier Login
res_cashier = client.post("/api/auth/login", json={"username": "cashier1", "password": "cashier123"})
assert res_cashier.status_code == 200, f"Cashier login failed: {res_cashier.text}"
cashier_data = res_cashier.json()
print("Cashier login OK:", cashier_data)
cashier_token = cashier_data["token"]
cashier_id = cashier_data["id"]

# Owner Login
res_owner = client.post("/api/auth/login", json={"username": "aunt", "password": "owner123"})
assert res_owner.status_code == 200, f"Owner login failed: {res_owner.text}"
owner_data = res_owner.json()
print("Owner login OK:", owner_data)
owner_token = owner_data["token"]

print("\n--- 2. Testing Menu Retrieval ---")
res_menu = client.get("/api/menu")
assert res_menu.status_code == 200, f"Get menu failed: {res_menu.text}"
menu = res_menu.json()
print(f"Retrieved {len(menu)} menu items.")
drinks = [m for m in menu if m["category"] == "drink"]
assert len(drinks) >= 5, "Expected at least 5 drinks"
first_drink = drinks[0]
print(f"Sample Drink: {first_drink['name']} | Stock: {first_drink['drink_inventory']['stock_quantity']} | Low stock? {first_drink['drink_inventory']['is_low_stock']}")

print("\n--- 3. Testing Drink Inventory Endpoint ---")
res_inv = client.get("/api/inventory/drinks")
assert res_inv.status_code == 200
inv_list = res_inv.json()
print(f"Retrieved {len(inv_list)} drink inventory rows.")

print("\n--- 4. Testing Role Protection ---")
# Cashier trying to update inventory (should be 403 Forbidden)
res_forbidden = client.patch(
    f"/api/inventory/drinks/{inv_list[0]['id']}",
    json={"stock_quantity": 100},
    headers={"X-Auth-Token": cashier_token},
)
assert res_forbidden.status_code == 403, f"Expected 403 for cashier, got {res_forbidden.status_code}"
print("RBAC check OK: Cashier forbidden from modifying inventory (HTTP 403).")

# Owner updating inventory
res_owner_update = client.patch(
    f"/api/inventory/drinks/{inv_list[0]['id']}",
    json={"stock_quantity": inv_list[0]["stock_quantity"]},
    headers={"X-Auth-Token": owner_token},
)
assert res_owner_update.status_code == 200
print("RBAC check OK: Owner successfully updated inventory.")

print("\n--- 5. Testing Order Creation & Stock Deduction ---")
# Get initial stock of Mosi Light
db = SessionLocal()
mosi_item = db.query(MenuItem).filter(MenuItem.name.like("%Mosi Light%")).first()
assert mosi_item is not None, "Mosi Light not found"
mosi_inv = db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == mosi_item.id).first()
initial_stock = mosi_inv.stock_quantity
meal_item = db.query(MenuItem).filter(MenuItem.category == "meal").first()
db.close()

print(f"Pre-order Mosi Light Stock: {initial_stock}")

order_payload = {
    "cashier_id": cashier_id,
    "payment_method": "cash",
    "items": [
        {"menu_item_id": meal_item.id, "quantity": 1},
        {"menu_item_id": mosi_item.id, "quantity": 2},
    ],
}

res_order = client.post(
    "/api/orders",
    json=order_payload,
    headers={"X-Auth-Token": cashier_token},
)
assert res_order.status_code == 201, f"Order creation failed: {res_order.text}"
order_data = res_order.json()
expected_total = meal_item.price_zmw * 1 + mosi_item.price_zmw * 2
print("Order created:", order_data["id"], "Total:", order_data["total_amount"], "Status:", order_data["payment_status"])
assert abs(order_data["total_amount"] - expected_total) < 0.01, f"Expected total {expected_total}, got {order_data['total_amount']}"
assert order_data["payment_status"] == "paid"

# Verify stock decremented in DB
db = SessionLocal()
mosi_inv_after = db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == mosi_item.id).first()
new_stock = mosi_inv_after.stock_quantity
db.close()

print(f"Post-order Mosi Light Stock: {new_stock}")
assert new_stock == initial_stock - 2, f"Stock should decrement by 2 (from {initial_stock} to {initial_stock - 2}), got {new_stock}"
print("Stock deduction check OK!")

print("\n--- 6. Testing Insufficient Stock Rejection ---")
excessive_order = {
    "cashier_id": cashier_id,
    "payment_method": "cash",
    "items": [
        {"menu_item_id": mosi_item.id, "quantity": 9999},
    ],
}
res_fail = client.post(
    "/api/orders",
    json=excessive_order,
    headers={"X-Auth-Token": cashier_token},
)
assert res_fail.status_code == 400, f"Expected 400, got {res_fail.status_code}: {res_fail.text}"
print(f"Insufficient stock rejection check OK: {res_fail.json()['detail']}")

print("\n--- 7. Testing Mobile Money Pending Status ---")
momo_order = {
    "cashier_id": cashier_id,
    "payment_method": "mobile_money",
    "items": [
        {"menu_item_id": mosi_item.id, "quantity": 1},
    ],
}
res_momo = client.post(
    "/api/orders",
    json=momo_order,
    headers={"X-Auth-Token": cashier_token},
)
assert res_momo.status_code == 201
momo_data = res_momo.json()
assert momo_data["payment_status"] == "pending"
print("Mobile money order created with status 'pending': OK!")

# Verify stock was NOT decremented for pending mobile money order
db = SessionLocal()
mosi_inv_momo = db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == mosi_item.id).first()
assert mosi_inv_momo.stock_quantity == new_stock, "Mobile money pending order should NOT deduct stock yet"
db.close()
print("Mobile money pending order did not deduct stock: OK!")

print("\nALL BACKEND API VERIFICATIONS PASSED!")
