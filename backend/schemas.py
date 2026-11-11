from datetime import datetime
from decimal import Decimal
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

try:
    from .money import zmw_to_ngwee, ngwee_to_zmw
except ImportError:
    from money import zmw_to_ngwee, ngwee_to_zmw


# ---------------------------------------------------------
# Auth Schemas
# ---------------------------------------------------------
class LoginRequest(BaseModel):
    tenant_slug: str = "aunts-lusaka"
    username: str
    password: str


class LoginResponse(BaseModel):
    id: int
    tenant_id: str
    tenant_slug: str
    username: str
    role: Literal["cashier", "owner"]
    access_token: str
    refresh_token: str
    token: str  # Alias for access_token


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


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

    @model_validator(mode="before")
    @classmethod
    def convert_money(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "price_zmw" not in data and "price_ngwee" in data:
                return {**data, "price_zmw": ngwee_to_zmw(data["price_ngwee"])}
            return data
        if hasattr(data, "menu_item") and getattr(data, "menu_item", None) is not None:
            return {
                "id": data.id,
                "menu_item_id": data.menu_item_id,
                "name": data.menu_item.name,
                "price_zmw": ngwee_to_zmw(data.menu_item.price_ngwee),
                "stock_quantity": data.stock_quantity,
                "low_stock_threshold": data.low_stock_threshold,
                "is_low_stock": data.stock_quantity <= data.low_stock_threshold,
            }
        return data


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

    @property
    def price_ngwee(self) -> int:
        return zmw_to_ngwee(self.price_zmw)


class MenuItemUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[Literal["meal", "drink", "extra"]] = None
    price_zmw: Optional[Decimal] = Field(default=None, gt=0)
    is_available: Optional[bool] = None

    @property
    def price_ngwee(self) -> Optional[int]:
        if self.price_zmw is None:
            return None
        return zmw_to_ngwee(self.price_zmw)


class MenuItemResponse(MenuItemBase):
    id: int
    drink_inventory: Optional[DrinkInventoryResponse] = None
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def convert_money(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "price_zmw" not in data and "price_ngwee" in data:
                return {**data, "price_zmw": ngwee_to_zmw(data["price_ngwee"])}
            return data
        if hasattr(data, "price_ngwee"):
            return {
                "id": data.id,
                "name": data.name,
                "category": data.category,
                "price_zmw": ngwee_to_zmw(data.price_ngwee),
                "is_available": data.is_available,
                "drink_inventory": getattr(data, "drink_inventory", None),
            }
        return data


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

    @model_validator(mode="before")
    @classmethod
    def convert_money(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "price_at_sale" not in data and "price_at_sale_ngwee" in data:
                return {**data, "price_at_sale": ngwee_to_zmw(data["price_at_sale_ngwee"])}
            return data
        if hasattr(data, "price_at_sale_ngwee"):
            return {
                "id": data.id,
                "order_id": data.order_id,
                "menu_item_id": data.menu_item_id,
                "quantity": data.quantity,
                "price_at_sale": ngwee_to_zmw(data.price_at_sale_ngwee),
            }
        return data


# ---------------------------------------------------------
# Order Schemas
# ---------------------------------------------------------
class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_method: Literal["cash", "mobile_money"]
    items: List[OrderItemCreate]


class OrderResponse(BaseModel):
    id: int
    cashier_id: int
    total_amount: float
    payment_method: Literal["cash", "mobile_money"]
    payment_status: Literal["pending", "paid", "failed", "expired"]
    lenco_reference: Optional[str] = None
    needs_review: bool = False
    review_reason: Optional[str] = None
    created_at: datetime
    items: List[OrderItemResponse] = []
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def convert_money(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "total_amount" not in data and "total_ngwee" in data:
                return {**data, "total_amount": ngwee_to_zmw(data["total_ngwee"])}
            return data
        if hasattr(data, "total_ngwee"):
            return {
                "id": data.id,
                "cashier_id": data.cashier_id,
                "total_amount": ngwee_to_zmw(data.total_ngwee),
                "payment_method": data.payment_method,
                "payment_status": data.payment_status,
                "lenco_reference": data.lenco_reference,
                "needs_review": bool(getattr(data, "needs_review", False)),
                "review_reason": getattr(data, "review_reason", None),
                "created_at": data.created_at,
                "items": getattr(data, "items", []),
            }
        return data


# ---------------------------------------------------------
# Payment & Webhook Schemas
# ---------------------------------------------------------
class MobileMoneyInitiateRequest(BaseModel):
    order_id: int
    phone: str
    operator: Literal["mtn", "airtel", "zamtel"]


class MobileMoneySubmitOtpRequest(BaseModel):
    order_id: int
    otp: str
    reference: Optional[str] = None


class MobileMoneyAbandonRequest(BaseModel):
    order_id: int
    reference: str


class MobileMoneyAbandonResponse(BaseModel):
    status: str
    order_id: int
    reference: str
    message: str


class MobileMoneyInitiateResponse(BaseModel):
    status: str
    message: str
    lenco_reference: str
    reference: Optional[str] = None
    attempt_id: Optional[int] = None
    provider_reference: Optional[str] = None


class LencoWebhookRequest(BaseModel):
    lenco_reference: str
    status: Literal["successful", "failed"]


class PaymentStatusResponse(BaseModel):
    order_id: int
    payment_status: Literal["pending", "paid", "failed", "expired"]
    status: Optional[str] = None
    lenco_reference: Optional[str] = None
    needs_review: bool = False
    review_reason: Optional[str] = None


class ReconciliationResponse(BaseModel):
    checked_count: int
    settled_paid_count: int
    settled_failed_count: int
    expired_count: int = 0
    still_pending_count: int
    error_count: int = 0


# ---------------------------------------------------------
# Dashboard & Analytics Schemas
# ---------------------------------------------------------
class DashboardSummaryResponse(BaseModel):
    today_total_revenue_zmw: float
    today_cash_revenue_zmw: float
    settlement_account_balance_zmw: float
    today_orders_count: int
    low_stock_alerts: List[DrinkInventoryWithItemResponse]
    needs_review_count: int = 0
    needs_review_orders: List[OrderResponse] = []

    @model_validator(mode="before")
    @classmethod
    def convert_money(cls, data: Any) -> Any:
        if isinstance(data, dict):
            out = dict(data)
            if "today_total_revenue_zmw" not in out and "today_total_revenue_ngwee" in out:
                out["today_total_revenue_zmw"] = ngwee_to_zmw(out.pop("today_total_revenue_ngwee"))
            if "today_cash_revenue_zmw" not in out and "today_cash_revenue_ngwee" in out:
                out["today_cash_revenue_zmw"] = ngwee_to_zmw(out.pop("today_cash_revenue_ngwee"))
            if (
                "settlement_account_balance_zmw" not in out
                and "settlement_account_balance_ngwee" in out
            ):
                out["settlement_account_balance_zmw"] = ngwee_to_zmw(
                    out.pop("settlement_account_balance_ngwee")
                )
            return out
        return data


class CalendarDayAnalytics(BaseModel):
    date: str  # YYYY-MM-DD
    total_revenue_zmw: float
    total_orders_count: int
    total_meals_sold: int

    @model_validator(mode="before")
    @classmethod
    def convert_money(cls, data: Any) -> Any:
        if isinstance(data, dict):
            out = dict(data)
            if "total_revenue_zmw" not in out and "total_revenue_ngwee" in out:
                out["total_revenue_zmw"] = ngwee_to_zmw(out.pop("total_revenue_ngwee"))
            return out
        return data
