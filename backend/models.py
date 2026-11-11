import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
    CheckConstraint,
    DateTime,
    Uuid,
)
from sqlalchemy.orm import relationship

try:
    from .database import Base
except ImportError:
    from database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, default="active", nullable=False)  # 'active' or 'suspended'
    timezone = Column(String, default="Africa/Lusaka", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="ck_tenants_status"),
    )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    username = Column(String, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # 'cashier' or 'owner'
    is_active = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),
        UniqueConstraint("id", "tenant_id", name="uq_users_id_tenant"),
    )

    orders = relationship(
        "Order",
        back_populates="cashier",
        primaryjoin="and_(User.id == Order.cashier_id, User.tenant_id == Order.tenant_id)",
        foreign_keys="[Order.cashier_id, Order.tenant_id]",
    )
    refresh_tokens = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        primaryjoin="and_(User.id == RefreshToken.user_id, User.tenant_id == RefreshToken.tenant_id)",
        foreign_keys="[RefreshToken.user_id, RefreshToken.tenant_id]",
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id = Column(Integer, nullable=False, index=True)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    jti = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_refresh_tokens_user_tenant",
        ),
    )

    user = relationship(
        "User",
        back_populates="refresh_tokens",
        primaryjoin="and_(RefreshToken.user_id == User.id, RefreshToken.tenant_id == User.tenant_id)",
        foreign_keys="[RefreshToken.user_id, RefreshToken.tenant_id]",
    )


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    name = Column(String, index=True, nullable=False)
    category = Column(String, nullable=False)  # 'meal', 'drink', 'extra'
    price_ngwee = Column(BigInteger, nullable=False)
    is_available = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_menu_items_tenant_name"),
        UniqueConstraint("id", "tenant_id", name="uq_menu_items_id_tenant"),
    )

    drink_inventory = relationship(
        "DrinkInventory",
        back_populates="menu_item",
        uselist=False,
        primaryjoin="and_(MenuItem.id == DrinkInventory.menu_item_id, MenuItem.tenant_id == DrinkInventory.tenant_id)",
        foreign_keys="[DrinkInventory.menu_item_id, DrinkInventory.tenant_id]",
    )
    order_items = relationship(
        "OrderItem",
        back_populates="menu_item",
        primaryjoin="and_(MenuItem.id == OrderItem.menu_item_id, MenuItem.tenant_id == OrderItem.tenant_id)",
        foreign_keys="[OrderItem.menu_item_id, OrderItem.tenant_id]",
        overlaps="items,order",
    )


class DrinkInventory(Base):
    __tablename__ = "drink_inventories"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    menu_item_id = Column(Integer, unique=True, nullable=False)
    stock_quantity = Column(Integer, default=0, nullable=False)  # whole units
    low_stock_threshold = Column(Integer, default=5, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["menu_item_id", "tenant_id"],
            ["menu_items.id", "menu_items.tenant_id"],
            name="fk_drink_inventories_menu_item_tenant",
        ),
    )

    menu_item = relationship(
        "MenuItem",
        back_populates="drink_inventory",
        primaryjoin="and_(DrinkInventory.menu_item_id == MenuItem.id, DrinkInventory.tenant_id == MenuItem.tenant_id)",
        foreign_keys="[DrinkInventory.menu_item_id, DrinkInventory.tenant_id]",
    )


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    cashier_id = Column(Integer, nullable=False)
    total_ngwee = Column(BigInteger, nullable=False)
    payment_method = Column(String, nullable=False)  # 'cash' or 'mobile_money'
    payment_status = Column(
        String, default="pending", nullable=False
    )  # 'pending', 'paid', 'failed', 'expired'
    lenco_reference = Column(String, unique=True, index=True, nullable=True)
    needs_review = Column(Boolean, default=False, nullable=False)
    review_reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_orders_id_tenant"),
        ForeignKeyConstraint(
            ["cashier_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_orders_cashier_tenant",
        ),
    )

    cashier = relationship(
        "User",
        back_populates="orders",
        primaryjoin="and_(Order.cashier_id == User.id, Order.tenant_id == User.tenant_id)",
        foreign_keys="[Order.cashier_id, Order.tenant_id]",
    )
    items = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        primaryjoin="and_(Order.id == OrderItem.order_id, Order.tenant_id == OrderItem.tenant_id)",
        foreign_keys="[OrderItem.order_id, OrderItem.tenant_id]",
        overlaps="order_items,menu_item",
    )
    payment_attempts = relationship(
        "PaymentAttempt",
        back_populates="order",
        cascade="all, delete-orphan",
        primaryjoin="and_(Order.id == PaymentAttempt.order_id, Order.tenant_id == PaymentAttempt.tenant_id)",
        foreign_keys="[PaymentAttempt.order_id, PaymentAttempt.tenant_id]",
        order_by="PaymentAttempt.id.asc()",
    )


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    order_id = Column(Integer, nullable=False, index=True)
    reference = Column(String, unique=True, index=True, nullable=False)
    lenco_reference = Column(String, index=True, nullable=True)
    status = Column(
        String, default="pending", nullable=False
    )  # 'pending', 'otp-required', 'pay-offline', 'successful', 'failed', 'expired'
    fee_ngwee = Column(BigInteger, nullable=True)
    fee_bearer = Column(String, nullable=True)
    settlement_status = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            name="fk_payment_attempts_order_tenant",
        ),
    )

    order = relationship(
        "Order",
        back_populates="payment_attempts",
        primaryjoin="and_(PaymentAttempt.order_id == Order.id, PaymentAttempt.tenant_id == Order.tenant_id)",
        foreign_keys="[PaymentAttempt.order_id, PaymentAttempt.tenant_id]",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    order_id = Column(Integer, nullable=False)
    menu_item_id = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    price_at_sale_ngwee = Column(BigInteger, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            name="fk_order_items_order_tenant",
        ),
        ForeignKeyConstraint(
            ["menu_item_id", "tenant_id"],
            ["menu_items.id", "menu_items.tenant_id"],
            name="fk_order_items_menu_item_tenant",
        ),
    )

    order = relationship(
        "Order",
        back_populates="items",
        primaryjoin="and_(OrderItem.order_id == Order.id, OrderItem.tenant_id == Order.tenant_id)",
        foreign_keys="[OrderItem.order_id, OrderItem.tenant_id]",
        overlaps="order_items,menu_item",
    )
    menu_item = relationship(
        "MenuItem",
        back_populates="order_items",
        primaryjoin="and_(OrderItem.menu_item_id == MenuItem.id, OrderItem.tenant_id == MenuItem.tenant_id)",
        foreign_keys="[OrderItem.menu_item_id, OrderItem.tenant_id]",
        overlaps="items,order",
    )
