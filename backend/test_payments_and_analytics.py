import sys
from fastapi.testclient import TestClient
from main import app
from database import SessionLocal
from models import DrinkInventory, MenuItem, Order, OrderItem, User
from seed import seed

# Reset database to fresh seed
print("Resetting database to initial clean state...")
seed()

client = TestClient(app)

print("\n--- 1. Authenticate Cashier & Owner ---")
res_cashier = client.post("/api/auth/login", json={"username": "cashier1", "password": "cashier123"})
assert res_cashier.status_code == 200
cashier_token = res_cashier.json()["token"]
cashier_id = res_cashier.json()["id"]

res_owner = client.post("/api/auth/login", json={"username": "aunt", "password": "owner123"})
assert res_owner.status_code == 200
owner_token = res_owner.json()["token"]
print("Auth OK: Cashier & Owner tokens retrieved.")

print("\n--- 2. Create Mobile Money Order with Meal & Drink ---")
db = SessionLocal()
meal = db.query(MenuItem).filter(MenuItem.category == "meal").first()
drink = db.query(MenuItem).filter(MenuItem.name.like("%Castle Lite%")).first()
drink_inv = db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == drink.id).first()
initial_drink_stock = drink_inv.stock_quantity
db.close()

print(f"Target Drink: {drink.name} | Initial Stock: {initial_drink_stock}")

order_payload = {
    "cashier_id": cashier_id,
    "payment_method": "mobile_money",
    "items": [
        {"menu_item_id": meal.id, "quantity": 2},  # 2 meals
        {"menu_item_id": drink.id, "quantity": 3}, # 3 drinks
    ],
}

res_order = client.post("/api/orders", json=order_payload, headers={"X-Auth-Token": cashier_token})
assert res_order.status_code == 201, f"Failed: {res_order.text}"
order_data = res_order.json()
order_id = order_data["id"]
expected_total = round(meal.price_zmw * 2 + drink.price_zmw * 3, 2)

print(f"Created Order #{order_id} | Status: {order_data['payment_status']} | Total: ZMW {order_data['total_amount']}")
assert order_data["payment_status"] == "pending"
assert order_data["total_amount"] == expected_total

# Verify stock has NOT decreased yet
db = SessionLocal()
drink_inv_check = db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == drink.id).first()
assert drink_inv_check.stock_quantity == initial_drink_stock, "Stock should NOT decrease while order is pending"
db.close()
print("Pending order stock check OK: Stock unchanged.")

print("\n--- 3. Testing Phone Validation & Payment Initiation ---")
# Invalid phone
res_bad_phone = client.post(
    "/api/payments/mobile-money/initiate",
    json={"order_id": order_id, "phone": "12345", "operator": "airtel"},
    headers={"X-Auth-Token": cashier_token},
)
assert res_bad_phone.status_code == 400
print("Phone validation check OK: Bad phone rejected with HTTP 400.")

# Valid phone
res_initiate = client.post(
    "/api/payments/mobile-money/initiate",
    json={"order_id": order_id, "phone": "0977123456", "operator": "airtel"},
    headers={"X-Auth-Token": cashier_token},
)
assert res_initiate.status_code == 200, f"Failed: {res_initiate.text}"
init_data = res_initiate.json()
lenco_ref = init_data["lenco_reference"]
print(f"Initiation OK: Reference generated -> {lenco_ref}")
assert lenco_ref.startswith(f"BOMA-{order_id}-")

print("\n--- 4. Polling Fallback Before Webhook ---")
res_poll_pre = client.get(f"/api/payments/status/{lenco_ref}")
assert res_poll_pre.status_code == 200
assert res_poll_pre.json()["payment_status"] == "pending"
print("Polling check OK: Returns pending.")

print("\n--- 5. Trigger Mock Lenco Webhook (Successful) ---")
res_webhook = client.post(
    "/api/webhooks/lenco",
    json={"lenco_reference": lenco_ref, "status": "successful"},
)
assert res_webhook.status_code == 200
print("Webhook responded:", res_webhook.json())

# Check Order Status is now Paid
res_poll_post = client.get(f"/api/payments/status/{lenco_ref}")
assert res_poll_post.status_code == 200
assert res_poll_post.json()["payment_status"] == "paid"
print("Order status is now 'paid': OK!")

# Check Drink Stock has decremented by 3
db = SessionLocal()
drink_inv_after = db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == drink.id).first()
expected_stock = initial_drink_stock - 3
print(f"Drink Stock After Payment: {drink_inv_after.stock_quantity} (Expected: {expected_stock})")
assert drink_inv_after.stock_quantity == expected_stock
db.close()
print("Stock deduction check OK!")

print("\n--- 6. Idempotency Test (Trigger Webhook a 2nd time) ---")
res_webhook2 = client.post(
    "/api/webhooks/lenco",
    json={"lenco_reference": lenco_ref, "status": "successful"},
)
assert res_webhook2.status_code == 200

# Verify stock did NOT decrement again
db = SessionLocal()
drink_inv_idem = db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == drink.id).first()
assert drink_inv_idem.stock_quantity == expected_stock, "Idempotency failed: Stock decremented twice!"
db.close()
print("Idempotency check OK: Stock NOT decremented on duplicate webhook.")

print("\n--- 7. Owner Dashboard Summary (RBAC + Analytics) ---")
# Cashier forbidden check
res_forbidden = client.get("/api/dashboard/summary", headers={"X-Auth-Token": cashier_token})
assert res_forbidden.status_code == 403
print("RBAC check OK: Cashier forbidden from dashboard summary (HTTP 403).")

# Owner summary
res_summary = client.get("/api/dashboard/summary", headers={"X-Auth-Token": owner_token})
assert res_summary.status_code == 200
summary = res_summary.json()
print("Owner Dashboard Summary:", summary)
assert summary["today_total_revenue_zmw"] == expected_total
assert summary["settlement_account_balance_zmw"] == expected_total  # mobile_money order
assert summary["today_cash_revenue_zmw"] == 0.0
assert summary["today_orders_count"] == 1
print("Summary metrics accurately reflect mobile money order!")

print("\n--- 8. Owner Calendar Analytics ---")
res_cal = client.get("/api/dashboard/calendar", headers={"X-Auth-Token": owner_token})
assert res_cal.status_code == 200
cal_data = res_cal.json()
print("Calendar Data:", cal_data)
assert len(cal_data) == 1
today_cal = cal_data[0]
assert today_cal["total_revenue_zmw"] == expected_total
assert today_cal["total_orders_count"] == 1
assert today_cal["total_meals_sold"] == 2  # We ordered 2 meals in that order!
print(f"Calendar check OK: Total Meals Sold = {today_cal['total_meals_sold']}, Revenue = {today_cal['total_revenue_zmw']}")

print("\n--- 9. Add Cash Order and Verify Combined Analytics ---")
meal2 = db.query(MenuItem).filter(MenuItem.name.like("%T-Bone%")).first()
order_cash = client.post(
    "/api/orders",
    json={
        "cashier_id": cashier_id,
        "payment_method": "cash",
        "items": [{"menu_item_id": meal2.id, "quantity": 1}],
    },
    headers={"X-Auth-Token": cashier_token},
)
assert order_cash.status_code == 201

res_summary2 = client.get("/api/dashboard/summary", headers={"X-Auth-Token": owner_token})
summary2 = res_summary2.json()
print("Updated Summary after Cash Order:", summary2)
assert summary2["today_cash_revenue_zmw"] == meal2.price_zmw
assert summary2["settlement_account_balance_zmw"] == expected_total
assert summary2["today_orders_count"] == 2
assert summary2["today_total_revenue_zmw"] == round(expected_total + meal2.price_zmw, 2)

res_cal2 = client.get("/api/dashboard/calendar", headers={"X-Auth-Token": owner_token})
cal2 = res_cal2.json()[0]
assert cal2["total_orders_count"] == 2
assert cal2["total_meals_sold"] == 3  # 2 from first order + 1 from second order
print(f"Combined Calendar OK: Meals Sold = {cal2['total_meals_sold']}, Total Orders = {cal2['total_orders_count']}")

print("\nALL LENCO MOBILE MONEY & OWNER ANALYTICS TESTS PASSED!")
