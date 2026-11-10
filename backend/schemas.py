from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------
# Auth Schemas
# ---------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    id: int
    username: str
    role: Literal["cashier", "owner"]
    token: str


# ---------------------------------------------------------
# User Schemas
# ---------------------------------------------------------
class UserBase(BaseModel):
    username: str
    role: Literal["cashier", "owner"]


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------
# DrinkInventory Schemas
# ---------------------------------------------------------
class DrinkInventoryBase(BaseModel):
    stock_quantity: int = Field(ge=0, description="Whole units in stock")
    low_stock_threshold: int = Field(default=5, ge=0)


class DrinkInventoryCreate(DrinkInventoryBase):
    menu_item_id: int


class DrinkInventoryUpdate(BaseModel):
    stock_quantity: Optional[int] = Field(default=None, ge=0)
    low_stock_threshold: Optional[int] = Field(default=None, ge=0)


class DrinkInventoryResponse(DrinkInventoryBase):
    id: int
    menu_item_id: int
    is_low_stock: Optional[bool] = None
    model_config = ConfigDict(from_attributes=True)


class DrinkInventoryWithItemResponse(BaseModel):
    id: int
    menu_item_id: int
    name: str
    price_zmw: float
    stock_quantity: int
    low_stock_threshold: int
    is_low_stock: bool
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------
# MenuItem Schemas
# ---------------------------------------------------------
class MenuItemBase(BaseModel):
    name: str
    category: Literal["meal", "drink", "extra"]
    price_zmw: float = Field(gt=0, description="Price in Zambian Kwacha")
    is_available: bool = True


class MenuItemCreate(MenuItemBase):
    initial_stock: Optional[int] = None
    low_stock_threshold: Optional[int] = 5


class MenuItemUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[Literal["meal", "drink", "extra"]] = None
    price_zmw: Optional[float] = Field(default=None, gt=0)
    is_available: Optional[bool] = None


class MenuItemResponse(MenuItemBase):
    id: int
    drink_inventory: Optional[DrinkInventoryResponse] = None
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------
# OrderItem Schemas
# ---------------------------------------------------------
class OrderItemCreate(BaseModel):
    menu_item_id: int
    quantity: int = Field(gt=0)


class OrderItemResponse(BaseModel):
    id: int
    order_id: int
    menu_item_id: int
    quantity: int
    price_at_sale: float
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------
# Order Schemas
# ---------------------------------------------------------
class OrderCreate(BaseModel):
    cashier_id: int
    payment_method: Literal["cash", "mobile_money"]
    items: List[OrderItemCreate]
    lenco_reference: Optional[str] = None


class OrderResponse(BaseModel):
    id: int
    cashier_id: int
    total_amount: float
    payment_method: Literal["cash", "mobile_money"]
    payment_status: Literal["pending", "paid", "failed"]
    lenco_reference: Optional[str] = None
    created_at: datetime
    items: List[OrderItemResponse] = []
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------
# Payment & Webhook Schemas
# ---------------------------------------------------------
class MobileMoneyInitiateRequest(BaseModel):
    order_id: int
    phone: str
    operator: Literal["mtn", "airtel", "zamtel"]


class MobileMoneyInitiateResponse(BaseModel):
    status: str
    message: str
    lenco_reference: str


class LencoWebhookRequest(BaseModel):
    lenco_reference: str
    status: Literal["successful", "failed"]


class PaymentStatusResponse(BaseModel):
    order_id: int
    payment_status: Literal["pending", "paid", "failed"]
    lenco_reference: Optional[str] = None


# ---------------------------------------------------------
# Dashboard & Analytics Schemas
# ---------------------------------------------------------
class DashboardSummaryResponse(BaseModel):
    today_total_revenue_zmw: float
    today_cash_revenue_zmw: float
    settlement_account_balance_zmw: float
    today_orders_count: int
    low_stock_alerts: List[DrinkInventoryWithItemResponse]


class CalendarDayAnalytics(BaseModel):
    date: str  # YYYY-MM-DD
    total_revenue_zmw: float
    total_orders_count: int
    total_meals_sold: int
