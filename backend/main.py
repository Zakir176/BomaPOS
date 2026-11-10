import re
import time
from datetime import datetime, date
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from passlib.context import CryptContext

try:
    from .database import engine, get_db, Base
    from .models import User, MenuItem, DrinkInventory, Order, OrderItem
    from .schemas import (
        LoginRequest,
        LoginResponse,
        MenuItemResponse,
        MenuItemUpdate,
        DrinkInventoryWithItemResponse,
        DrinkInventoryUpdate,
        OrderCreate,
        OrderResponse,
        MobileMoneyInitiateRequest,
        MobileMoneyInitiateResponse,
        LencoWebhookRequest,
        PaymentStatusResponse,
        DashboardSummaryResponse,
        CalendarDayAnalytics,
    )

    
except ImportError:
    from database import engine, get_db, Base
    from models import User, MenuItem, DrinkInventory, Order, OrderItem
    from schemas import (
        LoginRequest,
        LoginResponse,
        MenuItemResponse,
        MenuItemUpdate,
        DrinkInventoryWithItemResponse,
        DrinkInventoryUpdate,
        OrderCreate,
        OrderResponse,
        MobileMoneyInitiateRequest,
        MobileMoneyInitiateResponse,
        LencoWebhookRequest,
        PaymentStatusResponse,
        DashboardSummaryResponse,
        CalendarDayAnalytics,
    )

# Ensure tables exist
Base.metadata.create_all(bind=engine)

app = FastAPI(title="BomaPOS API", version="1.0.0")

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------
# Auth Dependencies & Helpers
# ---------------------------------------------------------
def create_local_token(user: User) -> str:
    # Clean local token format: "user_id:role:username"
    return f"{user.id}:{user.role}:{user.username}"


def get_current_user(
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
    db: Session = Depends(get_db),
) -> User:
    if not x_auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token in X-Auth-Token header",
        )

    parts = x_auth_token.split(":")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token format",
        )

    try:
        user_id = int(parts[0])
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.username != parts[2] or user.role != parts[1]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
        )

    return user


def require_owner(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation restricted to Owner role only",
        )
    return current_user


# ---------------------------------------------------------
# 1. Authentication Routes (FR-1.1 - FR-1.3)
# ---------------------------------------------------------
@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not pwd_context.verify(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_local_token(user)
    return LoginResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        token=token,
    )


# ---------------------------------------------------------
# 2. Menu Management (FR-2.1)
# ---------------------------------------------------------
@app.get("/api/menu", response_model=List[MenuItemResponse])
def get_menu(db: Session = Depends(get_db)):
    items = db.query(MenuItem).all()
    # Populate low stock indicator if item has drink inventory
    for item in items:
        if item.drink_inventory:
            item.drink_inventory.is_low_stock = (
                item.drink_inventory.stock_quantity <= item.drink_inventory.low_stock_threshold
            )
    return items


@app.patch("/api/menu/{item_id}", response_model=MenuItemResponse)
def update_menu_item(
    item_id: int,
    payload: MenuItemUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
):
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MenuItem with id {item_id} not found",
        )

    if payload.name is not None:
        item.name = payload.name
    if payload.category is not None:
        item.category = payload.category
    if payload.price_zmw is not None:
        item.price_zmw = payload.price_zmw
    if payload.is_available is not None:
        item.is_available = payload.is_available

    db.commit()
    db.refresh(item)
    return item


# ---------------------------------------------------------
# 3. Drink Inventory & Low-Stock Alerts (FR-4.1 - FR-4.3)
# ---------------------------------------------------------
@app.get("/api/inventory/drinks", response_model=List[DrinkInventoryWithItemResponse])
def get_drink_inventory(db: Session = Depends(get_db)):
    inventories = db.query(DrinkInventory).join(MenuItem).all()
    results = []
    for inv in inventories:
        results.append(
            DrinkInventoryWithItemResponse(
                id=inv.id,
                menu_item_id=inv.menu_item_id,
                name=inv.menu_item.name,
                price_zmw=inv.menu_item.price_zmw,
                stock_quantity=inv.stock_quantity,
                low_stock_threshold=inv.low_stock_threshold,
                is_low_stock=(inv.stock_quantity <= inv.low_stock_threshold),
            )
        )
    return results


@app.patch("/api/inventory/drinks/{drink_id}", response_model=DrinkInventoryWithItemResponse)
def update_drink_inventory(
    drink_id: int,
    payload: DrinkInventoryUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
):
    inv = db.query(DrinkInventory).filter(DrinkInventory.id == drink_id).first()
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DrinkInventory with id {drink_id} not found",
        )

    if payload.stock_quantity is not None:
        inv.stock_quantity = payload.stock_quantity
    if payload.low_stock_threshold is not None:
        inv.low_stock_threshold = payload.low_stock_threshold

    db.commit()
    db.refresh(inv)

    return DrinkInventoryWithItemResponse(
        id=inv.id,
        menu_item_id=inv.menu_item_id,
        name=inv.menu_item.name,
        price_zmw=inv.menu_item.price_zmw,
        stock_quantity=inv.stock_quantity,
        low_stock_threshold=inv.low_stock_threshold,
        is_low_stock=(inv.stock_quantity <= inv.low_stock_threshold),
    )


# ---------------------------------------------------------
# 4. POS Order Creation & Stock Deduction (FR-2.2 - FR-2.4, FR-4.2)
# ---------------------------------------------------------
@app.post("/api/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order must contain at least one item",
        )

    # Verify cashier exists
    cashier = db.query(User).filter(User.id == payload.cashier_id).first()
    if not cashier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cashier with id {payload.cashier_id} does not exist",
        )

    total_amount = 0.0
    order_items_to_create = []
    drink_inventories_to_decrement = []

    # Process items and calculate prices strictly from DB
    for item_in in payload.items:
        menu_item = db.query(MenuItem).filter(MenuItem.id == item_in.menu_item_id).first()
        if not menu_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"MenuItem with id {item_in.menu_item_id} not found",
            )
        if not menu_item.is_available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"MenuItem '{menu_item.name}' is currently marked unavailable",
            )

        # Check stock if item is a drink
        if menu_item.category == "drink":
            drink_inv = db.query(DrinkInventory).filter(DrinkInventory.menu_item_id == menu_item.id).first()
            if not drink_inv or drink_inv.stock_quantity < item_in.quantity:
                available = drink_inv.stock_quantity if drink_inv else 0
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Insufficient stock for {menu_item.name}. Available: {available}, Requested: {item_in.quantity}",
                )
            drink_inventories_to_decrement.append((drink_inv, item_in.quantity))

        item_total = menu_item.price_zmw * item_in.quantity
        total_amount += item_total

        order_items_to_create.append(
            OrderItem(
                menu_item_id=menu_item.id,
                quantity=item_in.quantity,
                price_at_sale=menu_item.price_zmw,
            )
        )

    # Payment logic
    if payload.payment_method == "cash":
        payment_status = "paid"
        # Immediate stock deduction for cash payments
        for drink_inv, qty in drink_inventories_to_decrement:
            drink_inv.stock_quantity -= qty
    else:  # mobile_money
        payment_status = "pending"
        # Stock will be deducted once mobile money payment confirms in webhook module

    new_order = Order(
        cashier_id=payload.cashier_id,
        total_amount=round(total_amount, 2),
        payment_method=payload.payment_method,
        payment_status=payment_status,
        lenco_reference=payload.lenco_reference,
    )
    new_order.items = order_items_to_create

    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    return new_order


# ---------------------------------------------------------
# 5. Mock Lenco Mobile Money Integration (FR-3.1 - FR-3.4)
# ---------------------------------------------------------
def normalize_zambian_phone(phone: str) -> str:
    cleaned = re.sub(r"[\s\-\(\)]", "", phone.strip())
    if cleaned.startswith("+260"):
        cleaned = cleaned[1:]
    elif cleaned.startswith("0"):
        cleaned = "260" + cleaned[1:]

    # Must be 12 digits starting with 260 and followed by 97, 96, 95, 77, 76, 75
    pattern = r"^260(97|96|95|77|76|75)\d{7}$"
    if not re.match(pattern, cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid Zambian phone number: '{phone}'. Expected 097/096/095/077/076/075 series or 260...",
        )
    return cleaned


@app.post("/api/payments/mobile-money/initiate", response_model=MobileMoneyInitiateResponse)
def initiate_mobile_money_payment(
    payload: MobileMoneyInitiateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == payload.order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with id {payload.order_id} not found",
        )

    if order.payment_status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order is not in pending status (current status: '{order.payment_status}')",
        )

    # Normalize phone
    normalize_zambian_phone(payload.phone)

    # Generate unique Lenco reference: BOMA-{order_id}-{unix_timestamp}
    timestamp = int(time.time())
    lenco_ref = f"BOMA-{order.id}-{timestamp}"
    order.lenco_reference = lenco_ref
    db.commit()

    return MobileMoneyInitiateResponse(
        status="pending",
        message="USSD push prompt simulated to customer phone",
        lenco_reference=lenco_ref,
    )


@app.post("/api/webhooks/lenco")
def lenco_webhook(
    payload: LencoWebhookRequest,
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter(Order.lenco_reference == payload.lenco_reference).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with lenco_reference '{payload.lenco_reference}' not found",
        )

    if payload.status == "successful":
        # IDEMPOTENCY: only process if not already marked paid
        if order.payment_status != "paid":
            order.payment_status = "paid"

            # Deduct ordered drink quantities from DrinkInventory
            for item in order.items:
                if item.menu_item and item.menu_item.category == "drink":
                    drink_inv = (
                        db.query(DrinkInventory)
                        .filter(DrinkInventory.menu_item_id == item.menu_item_id)
                        .first()
                    )
                    if drink_inv:
                        drink_inv.stock_quantity = max(0, drink_inv.stock_quantity - item.quantity)

            db.commit()
        return {"status": "success", "message": "Payment confirmed and drink stock updated"}

    elif payload.status == "failed":
        if order.payment_status != "paid":
            order.payment_status = "failed"
            db.commit()
        return {"status": "failed", "message": "Order marked as payment failed"}


@app.get("/api/payments/status/{lenco_reference}", response_model=PaymentStatusResponse)
def get_payment_status(
    lenco_reference: str,
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter(Order.lenco_reference == lenco_reference).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with lenco_reference '{lenco_reference}' not found",
        )

    return PaymentStatusResponse(
        order_id=order.id,
        payment_status=order.payment_status,
        lenco_reference=order.lenco_reference,
    )


# ---------------------------------------------------------
# 6. Owner Dashboards, Settlement & Analytics (FR-5.1 - FR-5.3)
# ---------------------------------------------------------
@app.get("/api/dashboard/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
):
    today = date.today()

    # Query all paid orders created today
    paid_orders_today = (
        db.query(Order)
        .filter(
            Order.payment_status == "paid",
            func.date(Order.created_at) == today.strftime("%Y-%m-%d"),
        )
        .all()
    )

    today_total_revenue = sum(o.total_amount for o in paid_orders_today)
    today_cash_revenue = sum(o.total_amount for o in paid_orders_today if o.payment_method == "cash")
    today_orders_count = len(paid_orders_today)

    # Settlement account balance = all-time total of paid mobile_money orders in sub-account
    paid_momo_orders = (
        db.query(Order)
        .filter(
            Order.payment_status == "paid",
            Order.payment_method == "mobile_money",
        )
        .all()
    )
    settlement_account_balance = sum(o.total_amount for o in paid_momo_orders)

    # Low stock alerts: drinks where stock_quantity <= low_stock_threshold
    low_stock_records = (
        db.query(DrinkInventory)
        .join(MenuItem)
        .filter(DrinkInventory.stock_quantity <= DrinkInventory.low_stock_threshold)
        .all()
    )

    low_stock_alerts = [
        DrinkInventoryWithItemResponse(
            id=inv.id,
            menu_item_id=inv.menu_item_id,
            name=inv.menu_item.name,
            price_zmw=inv.menu_item.price_zmw,
            stock_quantity=inv.stock_quantity,
            low_stock_threshold=inv.low_stock_threshold,
            is_low_stock=True,
        )
        for inv in low_stock_records
    ]

    return DashboardSummaryResponse(
        today_total_revenue_zmw=round(today_total_revenue, 2),
        today_cash_revenue_zmw=round(today_cash_revenue, 2),
        settlement_account_balance_zmw=round(settlement_account_balance, 2),
        today_orders_count=today_orders_count,
        low_stock_alerts=low_stock_alerts,
    )


@app.get("/api/dashboard/calendar", response_model=List[CalendarDayAnalytics])
def get_dashboard_calendar(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2020, le=2099),
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
):
    query = db.query(Order).filter(Order.payment_status == "paid")

    paid_orders = query.all()

    # Filter by month/year if supplied
    daily_groups = {}
    for o in paid_orders:
        order_date = o.created_at.date()
        if year and order_date.year != year:
            continue
        if month and order_date.month != month:
            continue

        date_str = order_date.strftime("%Y-%m-%d")
        if date_str not in daily_groups:
            daily_groups[date_str] = {
                "date": date_str,
                "total_revenue_zmw": 0.0,
                "total_orders_count": 0,
                "total_meals_sold": 0,
            }

        daily_groups[date_str]["total_revenue_zmw"] += o.total_amount
        daily_groups[date_str]["total_orders_count"] += 1

        for item in o.items:
            if item.menu_item and item.menu_item.category == "meal":
                daily_groups[date_str]["total_meals_sold"] += item.quantity

    # Sort results by date ascending
    results = [
        CalendarDayAnalytics(
            date=day_data["date"],
            total_revenue_zmw=round(day_data["total_revenue_zmw"], 2),
            total_orders_count=day_data["total_orders_count"],
            total_meals_sold=day_data["total_meals_sold"],
        )
        for _, day_data in sorted(daily_groups.items(), key=lambda x: x[0])
    ]

    return results
