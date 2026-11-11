import uuid
from passlib.context import CryptContext
from sqlalchemy.orm import Session

try:
    from .database import SessionLocal, AdminSessionLocal, bind_session_to_tenant
    from .models import (
        Tenant,
        User,
        MenuItem,
        DrinkInventory,
        Order,
        OrderItem,
        RefreshToken,
        PaymentAttempt,
    )
    from .money import zmw_to_ngwee
except ImportError:
    from database import SessionLocal, AdminSessionLocal, bind_session_to_tenant
    from models import (
        Tenant,
        User,
        MenuItem,
        DrinkInventory,
        Order,
        OrderItem,
        RefreshToken,
        PaymentAttempt,
    )
    from money import zmw_to_ngwee

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TENANT_A_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_B_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _seed_tenant_catalog(
    db: Session,
    tenant_id: uuid.UUID,
    price_multiplier_zmw: int = 0,
    stock_offset: int = 0,
) -> None:
    bind_session_to_tenant(db, tenant_id)

    users = [
        User(
            tenant_id=tenant_id,
            username="aunt",
            password_hash=hash_password("owner123"),
            role="owner",
        ),
        User(
            tenant_id=tenant_id,
            username="cashier1",
            password_hash=hash_password("cashier123"),
            role="cashier",
        ),
    ]
    db.add_all(users)
    db.commit()

    meals_data = [
        ("Nshima with T-Bone", 95 + price_multiplier_zmw),
        ("Nshima with Village Chicken", 85 + price_multiplier_zmw),
        ("Nshima with Bream Fish", 90 + price_multiplier_zmw),
        ("Chips & Sausage", 50 + price_multiplier_zmw),
        ("Beef Stew with Rice", 75 + price_multiplier_zmw),
    ]
    meals = [
        MenuItem(
            tenant_id=tenant_id,
            name=name,
            category="meal",
            price_ngwee=zmw_to_ngwee(f"{price:.2f}"),
            is_available=True,
        )
        for name, price in meals_data
    ]
    db.add_all(meals)
    db.commit()

    drinks_data = [
        {"name": "Mosi Light 330ml", "price_zmw": 25 + price_multiplier_zmw, "stock": 48 + stock_offset, "low_threshold": 12},
        {"name": "Castle Lite 330ml", "price_zmw": 25 + price_multiplier_zmw, "stock": 36 + stock_offset, "low_threshold": 10},
        {"name": "Coca-Cola 500ml", "price_zmw": 18 + price_multiplier_zmw, "stock": 60 + stock_offset, "low_threshold": 15},
        {"name": "Fanta Orange 500ml", "price_zmw": 18 + price_multiplier_zmw, "stock": 40 + stock_offset, "low_threshold": 10},
        {"name": "Bottled Mineral Water 500ml", "price_zmw": 10 + price_multiplier_zmw, "stock": 72 + stock_offset, "low_threshold": 20},
    ]

    for drink in drinks_data:
        item = MenuItem(
            tenant_id=tenant_id,
            name=drink["name"],
            category="drink",
            price_ngwee=zmw_to_ngwee(f"{drink['price_zmw']:.2f}"),
            is_available=True,
        )
        db.add(item)
        db.flush()

        inv = DrinkInventory(
            tenant_id=tenant_id,
            menu_item_id=item.id,
            stock_quantity=drink["stock"],
            low_stock_threshold=drink["low_threshold"],
        )
        db.add(inv)

    db.commit()


def seed():
    # Use AdminSessionLocal to clear existing data across all tenants cleanly
    admin_db: Session = AdminSessionLocal()
    try:
        admin_db.query(PaymentAttempt).delete()
        admin_db.query(OrderItem).delete()
        admin_db.query(Order).delete()
        admin_db.query(DrinkInventory).delete()
        admin_db.query(MenuItem).delete()
        admin_db.query(RefreshToken).delete()
        admin_db.query(User).delete()
        admin_db.query(Tenant).delete()
        admin_db.commit()

        print("Seeding two tenants (aunts-lusaka & boma-kitwe)...")
        tenant_a = Tenant(
            id=TENANT_A_ID,
            name="Aunt's Kitchen Lusaka",
            slug="aunts-lusaka",
            status="active",
            timezone="Africa/Lusaka",
        )
        tenant_b = Tenant(
            id=TENANT_B_ID,
            name="Boma Grill Kitwe",
            slug="boma-kitwe",
            status="active",
            timezone="Africa/Lusaka",
        )
        admin_db.add_all([tenant_a, tenant_b])
        admin_db.commit()
    except Exception as e:
        admin_db.rollback()
        print(f"Error resetting/creating tenants: {e}")
        raise e
    finally:
        admin_db.close()

    # Seed each tenant using the non-superuser app session bound to that tenant (verifies RLS on insert)
    db: Session = SessionLocal()
    try:
        print("Seeding Tenant A (aunts-lusaka) with overlapping usernames and menu item names...")
        _seed_tenant_catalog(db, TENANT_A_ID, price_multiplier_zmw=0, stock_offset=0)

        print("Seeding Tenant B (boma-kitwe) with overlapping usernames and menu item names...")
        _seed_tenant_catalog(db, TENANT_B_ID, price_multiplier_zmw=10, stock_offset=20)

        print("Database seeded successfully with two isolated tenants!")
    except Exception as e:
        db.rollback()
        print(f"Error seeding tenant catalogs: {e}")
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed()
