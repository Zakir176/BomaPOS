from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import engine, SessionLocal, Base
from models import User, MenuItem, DrinkInventory, Order, OrderItem

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def seed():
    print("Initializing database tables...")
    Base.metadata.create_all(bind=engine)

    db: Session = SessionLocal()
    try:
        # Clear existing data to ensure clean idempotent seed
        db.query(OrderItem).delete()
        db.query(Order).delete()
        db.query(DrinkInventory).delete()
        db.query(MenuItem).delete()
        db.query(User).delete()
        db.commit()

        print("Seeding Users...")
        users = [
            User(
                username="aunt",
                password_hash=hash_password("owner123"),
                role="owner",
            ),
            User(
                username="cashier1",
                password_hash=hash_password("cashier123"),
                role="cashier",
            ),
        ]
        db.add_all(users)
        db.commit()

        print("Seeding Meals...")
        meals = [
            MenuItem(name="Nshima with T-Bone", category="meal", price_zmw=95.0, is_available=True),
            MenuItem(name="Nshima with Village Chicken", category="meal", price_zmw=85.0, is_available=True),
            MenuItem(name="Nshima with Bream Fish", category="meal", price_zmw=90.0, is_available=True),
            MenuItem(name="Chips & Sausage", category="meal", price_zmw=50.0, is_available=True),
            MenuItem(name="Beef Stew with Rice", category="meal", price_zmw=75.0, is_available=True),
        ]
        db.add_all(meals)
        db.commit()

        print("Seeding Drinks & DrinkInventory...")
        drinks_data = [
            {"name": "Mosi Light 330ml", "price_zmw": 25.0, "stock": 48, "low_threshold": 12},
            {"name": "Castle Lite 330ml", "price_zmw": 25.0, "stock": 36, "low_threshold": 10},
            {"name": "Coca-Cola 500ml", "price_zmw": 18.0, "stock": 60, "low_threshold": 15},
            {"name": "Fanta Orange 500ml", "price_zmw": 18.0, "stock": 40, "low_threshold": 10},
            {"name": "Bottled Mineral Water 500ml", "price_zmw": 10.0, "stock": 72, "low_threshold": 20},
        ]

        for drink in drinks_data:
            item = MenuItem(
                name=drink["name"],
                category="drink",
                price_zmw=drink["price_zmw"],
                is_available=True,
            )
            db.add(item)
            db.flush()  # Generate item.id

            inv = DrinkInventory(
                menu_item_id=item.id,
                stock_quantity=drink["stock"],
                low_stock_threshold=drink["low_threshold"],
            )
            db.add(inv)

        db.commit()
        print("Database seeded successfully with initial users, meals, and drinks!")

    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed()
