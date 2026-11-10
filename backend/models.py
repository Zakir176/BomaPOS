from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship

try:
    from .database import Base
except ImportError:
    from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # 'cashier' or 'owner'

    orders = relationship("Order", back_populates="cashier")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    category = Column(String, nullable=False)  # 'meal', 'drink', 'extra'
    price_zmw = Column(Float, nullable=False)
    is_available = Column(Boolean, default=True, nullable=False)

    drink_inventory = relationship("DrinkInventory", back_populates="menu_item", uselist=False)
    order_items = relationship("OrderItem", back_populates="menu_item")


class DrinkInventory(Base):
    __tablename__ = "drink_inventories"

    id = Column(Integer, primary_key=True, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), unique=True, nullable=False)
    stock_quantity = Column(Integer, default=0, nullable=False)  # whole units
    low_stock_threshold = Column(Integer, default=5, nullable=False)

    menu_item = relationship("MenuItem", back_populates="drink_inventory")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    cashier_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    total_amount = Column(Float, nullable=False)
    payment_method = Column(String, nullable=False)  # 'cash' or 'mobile_money'
    payment_status = Column(String, default="pending", nullable=False)  # 'pending', 'paid', 'failed'
    lenco_reference = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    cashier = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price_at_sale = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    menu_item = relationship("MenuItem", back_populates="order_items")
