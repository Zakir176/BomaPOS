import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Header, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, case, cast, Date, extract, update, text, or_, and_
from passlib.context import CryptContext

load_dotenv()

try:
    from .database import SessionLocal, get_db, bind_session_to_tenant
    from .lenco_client import (
        ACTIVE_ATTEMPT_STATUSES,
        LencoClient,
        LencoCollectionResult,
        LencoRejectedError,
        LencoUnavailableError,
        format_zambian_phone,
        get_lenco_client,
        verify_lenco_webhook_signature,
    )
    from .models import (
        Tenant,
        User,
        RefreshToken,
        MenuItem,
        DrinkInventory,
        Order,
        OrderItem,
        PaymentAttempt,
    )
    from .schemas import (
        LoginRequest,
        LoginResponse,
        RefreshTokenRequest,
        TokenPairResponse,
        LogoutRequest,
        MenuItemResponse,
        MenuItemUpdate,
        DrinkInventoryWithItemResponse,
        DrinkInventoryUpdate,
        OrderCreate,
        OrderResponse,
        MobileMoneyInitiateRequest,
        MobileMoneySubmitOtpRequest,
        MobileMoneyAbandonRequest,
        MobileMoneyAbandonResponse,
        MobileMoneyInitiateResponse,
        PaymentStatusResponse,
        ReconciliationResponse,
        DashboardSummaryResponse,
        CalendarDayAnalytics,
    )
except ImportError:
    from database import SessionLocal, get_db, bind_session_to_tenant
    from lenco_client import (
        ACTIVE_ATTEMPT_STATUSES,
        LencoClient,
        LencoCollectionResult,
        LencoRejectedError,
        LencoUnavailableError,
        format_zambian_phone,
        get_lenco_client,
        verify_lenco_webhook_signature,
    )
    from models import (
        Tenant,
        User,
        RefreshToken,
        MenuItem,
        DrinkInventory,
        Order,
        OrderItem,
        PaymentAttempt,
    )
    from schemas import (
        LoginRequest,
        LoginResponse,
        RefreshTokenRequest,
        TokenPairResponse,
        LogoutRequest,
        MenuItemResponse,
        MenuItemUpdate,
        DrinkInventoryWithItemResponse,
        DrinkInventoryUpdate,
        OrderCreate,
        OrderResponse,
        MobileMoneyInitiateRequest,
        MobileMoneySubmitOtpRequest,
        MobileMoneyAbandonRequest,
        MobileMoneyAbandonResponse,
        MobileMoneyInitiateResponse,
        PaymentStatusResponse,
        ReconciliationResponse,
        DashboardSummaryResponse,
        CalendarDayAnalytics,
    )

logger = logging.getLogger("bomapos")

BUSINESS_TIMEZONE = "Africa/Lusaka"
LUSAKA_TZ = ZoneInfo(BUSINESS_TIMEZONE)

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7
MIN_JWT_SECRET_LEN = 32


def validate_jwt_secret(secret: Optional[str] = None) -> str:
    val = secret if secret is not None else os.environ.get("JWT_SECRET", "")
    if not val or len(val.strip()) < MIN_JWT_SECRET_LEN:
        raise RuntimeError(
            f"JWT_SECRET environment variable must be set and at least {MIN_JWT_SECRET_LEN} characters long"
        )
    return val


# Fail startup immediately if JWT_SECRET is missing or too short
JWT_SECRET = validate_jwt_secret()


def get_cron_secret() -> str:
    return os.environ.get("CRON_SECRET", "").strip()


def validate_cron_secret(
    lenco_mode: Optional[str] = None,
    cron_secret: Optional[str] = None,
) -> Optional[str]:
    mode = (
        lenco_mode
        if lenco_mode is not None
        else os.environ.get("LENCO_MODE", "mock")
    ).strip().lower()
    secret = (
        cron_secret
        if cron_secret is not None
        else get_cron_secret()
    ).strip()
    if mode == "live" and not secret:
        raise RuntimeError(
            "CRON_SECRET environment variable must be set when LENCO_MODE=live"
        )
    return secret


def validate_startup_config(
    lenco_mode: Optional[str] = None,
    lenco_api_token: Optional[str] = None,
    cron_secret: Optional[str] = None,
) -> None:
    """
    Ensure required environment variables are set on startup.
    When LENCO_MODE=live, both LENCO_API_TOKEN and CRON_SECRET are strictly required.
    """
    mode = (
        lenco_mode
        if lenco_mode is not None
        else os.environ.get("LENCO_MODE", "mock")
    ).strip().lower()
    if mode == "live":
        token = (
            lenco_api_token
            if lenco_api_token is not None
            else os.environ.get("LENCO_API_TOKEN", "")
        ).strip()
        if not token:
            raise RuntimeError(
                "LENCO_API_TOKEN environment variable is required when LENCO_MODE=live"
            )
        secret = (
            cron_secret
            if cron_secret is not None
            else get_cron_secret()
        ).strip()
        if not secret:
            raise RuntimeError(
                "CRON_SECRET environment variable must be set when LENCO_MODE=live"
            )


# Fail startup if LENCO_API_TOKEN or CRON_SECRET is missing in live mode
validate_startup_config()
validate_cron_secret()


def parse_allowed_origins(raw_origins: Optional[str] = None) -> List[str]:
    raw = (
        raw_origins
        if raw_origins is not None
        else os.environ.get(
            "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        )
    )
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if not origins or "*" in origins:
        raise RuntimeError(
            "ALLOWED_ORIGINS must be a non-empty comma-separated list of explicit origins without wildcard '*'"
        )
    return origins


ALLOWED_ORIGINS = parse_allowed_origins()

app = FastAPI(title="BomaPOS API", version="1.0.0")

# Restrict CORS to explicit ALLOWED_ORIGINS list (no wildcard '*')
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Basic in-memory login rate limiter (sliding window per client IP + username/tenant)
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 60
_login_attempts: Dict[str, List[float]] = {}


def reset_login_rate_limiter() -> None:
    _login_attempts.clear()


def _check_login_rate_limit(key: str) -> None:
    now = time.monotonic()
    window_start = now - LOGIN_RATE_LIMIT_WINDOW_SECONDS
    history = [ts for ts in _login_attempts.get(key, []) if ts > window_start]
    if len(history) >= LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
        _login_attempts[key] = history
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later.",
        )
    _login_attempts[key] = history


def _record_failed_login(key: str) -> None:
    now = time.monotonic()
    window_start = now - LOGIN_RATE_LIMIT_WINDOW_SECONDS
    history = [ts for ts in _login_attempts.get(key, []) if ts > window_start]
    history.append(now)
    _login_attempts[key] = history


def _clear_login_attempts(key: str) -> None:
    _login_attempts.pop(key, None)


# ---------------------------------------------------------
# JWT & Refresh Token Helpers
# ---------------------------------------------------------
def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_access_token(
    user_id: int,
    tenant_id: uuid.UUID,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    now = datetime.now(timezone.utc)
    exp = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token_jwt(
    user_id: int,
    tenant_id: uuid.UUID,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> Tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    exp = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )
    jti = str(uuid.uuid4())
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": jti,
        "type": "refresh",
    }
    encoded = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded, jti, exp


def decode_and_verify_jwt(token: str, expected_type: str = "access") -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authentication token",
        )

    if header.get("alg") != JWT_ALGORITHM:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signing algorithm",
        )

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "tenant_id", "role", "exp", "iat", "jti"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    token_type = payload.get("type", "access")
    if token_type != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Expected {expected_type} token",
        )

    return payload


def _extract_bearer_token(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization Bearer token",
        )
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'",
        )
    return parts[1].strip()


# ---------------------------------------------------------
# Request-Scoped Tenant Session & Auth Dependencies
# ---------------------------------------------------------
def get_tenant_db(
    token: str = Depends(_extract_bearer_token),
    db: Session = Depends(get_db),
) -> Session:
    """
    Single request-scoped dependency that verifies the JWT, checks that both the
    tenant and user are active, and yields a DB session bound to the verified tenant
    with Postgres RLS configured via set_config('app.current_tenant', :id, true).
    """
    claims = decode_and_verify_jwt(token, expected_type="access")

    try:
        user_id = int(claims["sub"])
        tenant_id = uuid.UUID(str(claims["tenant_id"]))
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
        )

    role = claims.get("role")
    if role not in ("cashier", "owner"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid role in token",
        )

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant or tenant.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant is suspended or does not exist",
        )

    bind_session_to_tenant(db, tenant.id)

    user = (
        db.query(User)
        .filter(User.id == user_id, User.tenant_id == tenant.id)
        .first()
    )
    if not user or not user.is_active or user.role != role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is inactive or invalid",
        )

    db.info["current_user"] = user
    db.info["current_tenant"] = tenant
    return db


def get_current_user(
    db: Session = Depends(get_tenant_db),
) -> User:
    return db.info["current_user"]


def require_owner(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation restricted to Owner role only",
        )
    return current_user


def _issue_token_pair(db: Session, user: User) -> Tuple[str, str]:
    access_token = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )
    refresh_token, jti, expires_at = create_refresh_token_jwt(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )
    rt_record = RefreshToken(
        tenant_id=user.tenant_id,
        user_id=user.id,
        token_hash=hash_refresh_token(refresh_token),
        jti=jti,
        expires_at=expires_at,
    )
    db.add(rt_record)
    db.commit()
    return access_token, refresh_token


# ---------------------------------------------------------
# 1. Authentication Routes (Login, Refresh Rotation, Logout)
# ---------------------------------------------------------
@app.post("/api/auth/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    x_tenant_slug: Optional[str] = Header(None, alias="X-Tenant-Slug"),
    db: Session = Depends(get_db),
):
    raw_username = payload.username.strip()
    tenant_slug = (x_tenant_slug or payload.tenant_slug or "aunts-lusaka").strip()
    if "/" in raw_username and not x_tenant_slug:
        tenant_slug, raw_username = raw_username.split("/", 1)

    client_ip = request.client.host if request.client else "local"
    rate_key = f"{client_ip}:{tenant_slug}:{raw_username}"
    _check_login_rate_limit(rate_key)

    tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
    if not tenant or tenant.status != "active":
        _record_failed_login(rate_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid tenant, username, or password",
        )

    bind_session_to_tenant(db, tenant.id)

    user = (
        db.query(User)
        .filter(User.tenant_id == tenant.id, User.username == raw_username)
        .first()
    )
    if (
        not user
        or not user.is_active
        or not pwd_context.verify(payload.password, user.password_hash)
    ):
        _record_failed_login(rate_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid tenant, username, or password",
        )

    _clear_login_attempts(rate_key)
    access_token, refresh_token = _issue_token_pair(db, user)

    return LoginResponse(
        id=user.id,
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        username=user.username,
        role=user.role,
        access_token=access_token,
        refresh_token=refresh_token,
        token=access_token,
    )


@app.post("/api/auth/refresh", response_model=TokenPairResponse)
def refresh_tokens(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    claims = decode_and_verify_jwt(payload.refresh_token, expected_type="refresh")

    try:
        user_id = int(claims["sub"])
        tenant_id = uuid.UUID(str(claims["tenant_id"]))
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token claims",
        )

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant or tenant.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant is suspended or does not exist",
        )

    bind_session_to_tenant(db, tenant.id)

    token_hash = hash_refresh_token(payload.refresh_token)
    stored_token = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.tenant_id == tenant.id,
            RefreshToken.token_hash == token_hash,
        )
        .first()
    )

    now = datetime.now(timezone.utc)
    if (
        not stored_token
        or stored_token.revoked_at is not None
        or stored_token.expires_at <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked or expired",
        )

    user = (
        db.query(User)
        .filter(User.id == user_id, User.tenant_id == tenant.id)
        .first()
    )
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is inactive or does not exist",
        )

    # Rotate refresh token: revoke the current refresh token and issue a fresh pair
    stored_token.revoked_at = now
    access_token, new_refresh_token = _issue_token_pair(db, user)

    return TokenPairResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token=access_token,
    )


@app.post("/api/auth/logout")
def logout(
    payload: Optional[LogoutRequest] = None,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
):
    claims = None
    if authorization:
        raw_access = _extract_bearer_token(authorization)
        claims = decode_and_verify_jwt(raw_access, expected_type="access")
    elif payload and payload.refresh_token:
        claims = decode_and_verify_jwt(payload.refresh_token, expected_type="refresh")
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization Bearer token or refresh_token",
        )

    try:
        user_id = int(claims["sub"])
        tenant_id = uuid.UUID(str(claims["tenant_id"]))
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
        )

    bind_session_to_tenant(db, tenant_id)
    now = datetime.now(timezone.utc)

    if payload and payload.refresh_token:
        th = hash_refresh_token(payload.refresh_token)
        rt = (
            db.query(RefreshToken)
            .filter(
                RefreshToken.tenant_id == tenant_id,
                RefreshToken.user_id == user_id,
                RefreshToken.token_hash == th,
            )
            .first()
        )
        if rt and rt.revoked_at is None:
            rt.revoked_at = now
    else:
        # Revoke all active refresh tokens for this user in this tenant
        active_tokens = (
            db.query(RefreshToken)
            .filter(
                RefreshToken.tenant_id == tenant_id,
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .all()
        )
        for rt in active_tokens:
            rt.revoked_at = now

    db.commit()
    return {"status": "logged_out"}


# ---------------------------------------------------------
# 2. Menu Management (FR-2.1)
# ---------------------------------------------------------
@app.get("/api/menu", response_model=List[MenuItemResponse])
def get_menu(
    db: Session = Depends(get_tenant_db),
    _: User = Depends(get_current_user),
):
    tenant_id = db.info["tenant_id"]
    items = db.query(MenuItem).filter(MenuItem.tenant_id == tenant_id).all()
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
    db: Session = Depends(get_tenant_db),
    _: User = Depends(require_owner),
):
    tenant_id = db.info["tenant_id"]
    item = (
        db.query(MenuItem)
        .filter(MenuItem.id == item_id, MenuItem.tenant_id == tenant_id)
        .first()
    )
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MenuItem with id {item_id} not found",
        )

    if payload.name is not None:
        item.name = payload.name
    if payload.category is not None:
        item.category = payload.category
    if payload.price_ngwee is not None:
        item.price_ngwee = payload.price_ngwee
    if payload.is_available is not None:
        item.is_available = payload.is_available

    db.commit()
    db.refresh(item)
    return item


# ---------------------------------------------------------
# 3. Drink Inventory & Low-Stock Alerts (FR-4.1 - FR-4.3)
# ---------------------------------------------------------
@app.get("/api/inventory/drinks", response_model=List[DrinkInventoryWithItemResponse])
def get_drink_inventory(
    db: Session = Depends(get_tenant_db),
    _: User = Depends(get_current_user),
):
    tenant_id = db.info["tenant_id"]
    inventories = (
        db.query(DrinkInventory)
        .join(
            MenuItem,
            (MenuItem.id == DrinkInventory.menu_item_id)
            & (MenuItem.tenant_id == DrinkInventory.tenant_id),
        )
        .filter(DrinkInventory.tenant_id == tenant_id)
        .all()
    )
    return [DrinkInventoryWithItemResponse.model_validate(inv) for inv in inventories]


@app.patch("/api/inventory/drinks/{drink_id}", response_model=DrinkInventoryWithItemResponse)
def update_drink_inventory(
    drink_id: int,
    payload: DrinkInventoryUpdate,
    db: Session = Depends(get_tenant_db),
    _: User = Depends(require_owner),
):
    tenant_id = db.info["tenant_id"]
    inv = (
        db.query(DrinkInventory)
        .filter(DrinkInventory.id == drink_id, DrinkInventory.tenant_id == tenant_id)
        .first()
    )
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

    return DrinkInventoryWithItemResponse.model_validate(inv)


def deduct_drink_stock_atomically(
    db: Session, tenant_id: uuid.UUID, menu_item: MenuItem, quantity: int
) -> None:
    """Atomically decrement tenant-scoped drink stock using UPDATE ... WHERE stock_quantity >= qty."""
    stmt = (
        update(DrinkInventory)
        .where(
            DrinkInventory.tenant_id == tenant_id,
            DrinkInventory.menu_item_id == menu_item.id,
            DrinkInventory.stock_quantity >= quantity,
        )
        .values(stock_quantity=DrinkInventory.stock_quantity - quantity)
        .execution_options(synchronize_session=False)
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock for {menu_item.name}. Requested: {quantity}",
        )


def deduct_drink_stock_clamped_for_settlement(
    db: Session, tenant_id: uuid.UUID, menu_item: MenuItem, quantity: int
) -> Optional[str]:
    """
    Decrement drink stock for a verified successful payment settlement without ever failing.
    If stock is sufficient, decrements atomically and returns None.
    If stock is insufficient, clamps stock_quantity at 0 and returns a short shortfall reason.
    """
    stmt = (
        update(DrinkInventory)
        .where(
            DrinkInventory.tenant_id == tenant_id,
            DrinkInventory.menu_item_id == menu_item.id,
            DrinkInventory.stock_quantity >= quantity,
        )
        .values(stock_quantity=DrinkInventory.stock_quantity - quantity)
        .execution_options(synchronize_session=False)
    )
    result = db.execute(stmt)
    if result.rowcount > 0:
        return None

    inv = (
        db.query(DrinkInventory)
        .filter(
            DrinkInventory.tenant_id == tenant_id,
            DrinkInventory.menu_item_id == menu_item.id,
        )
        .with_for_update()
        .first()
    )
    available = inv.stock_quantity if inv is not None else 0
    clamp_stmt = (
        update(DrinkInventory)
        .where(
            DrinkInventory.tenant_id == tenant_id,
            DrinkInventory.menu_item_id == menu_item.id,
        )
        .values(
            stock_quantity=func.greatest(DrinkInventory.stock_quantity - quantity, 0)
        )
        .execution_options(synchronize_session=False)
    )
    db.execute(clamp_stmt)
    return f"Stock shortfall on {menu_item.name} (needed {quantity}, had {available})"


# ---------------------------------------------------------
# 4. POS Order Creation & Stock Deduction (FR-2.2 - FR-2.4, FR-4.2)
# ---------------------------------------------------------
@app.post("/api/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = db.info["tenant_id"]

    if not payload.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order must contain at least one item",
        )

    total_ngwee = 0
    order_items_to_create = []
    drinks_to_decrement = []

    for item_in in payload.items:
        menu_item = (
            db.query(MenuItem)
            .filter(MenuItem.id == item_in.menu_item_id, MenuItem.tenant_id == tenant_id)
            .first()
        )
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

        if menu_item.category == "drink":
            drinks_to_decrement.append((menu_item, item_in.quantity))

        item_total_ngwee = menu_item.price_ngwee * item_in.quantity
        total_ngwee += item_total_ngwee

        order_items_to_create.append(
            OrderItem(
                tenant_id=tenant_id,
                menu_item_id=menu_item.id,
                quantity=item_in.quantity,
                price_at_sale_ngwee=menu_item.price_ngwee,
            )
        )

    if payload.payment_method == "cash":
        payment_status = "paid"
        for drink_item, qty in drinks_to_decrement:
            deduct_drink_stock_atomically(db, tenant_id, drink_item, qty)
    else:  # mobile_money
        payment_status = "pending"
        for drink_item, qty in drinks_to_decrement:
            has_stock = (
                db.query(DrinkInventory.id)
                .filter(
                    DrinkInventory.tenant_id == tenant_id,
                    DrinkInventory.menu_item_id == drink_item.id,
                    DrinkInventory.stock_quantity >= qty,
                )
                .first()
            )
            if not has_stock:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Insufficient stock for {drink_item.name}. Requested: {qty}",
                )

    # Always use the authenticated user (current_user.id) as the cashier
    new_order = Order(
        tenant_id=tenant_id,
        cashier_id=current_user.id,
        total_ngwee=total_ngwee,
        payment_method=payload.payment_method,
        payment_status=payment_status,
        lenco_reference=None,
    )
    new_order.items = order_items_to_create

    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    return new_order


# ---------------------------------------------------------
# 5. Lenco Mobile Money Integration, Webhook & Reconciliation
# ---------------------------------------------------------
normalize_zambian_phone = format_zambian_phone


PAYMENT_ATTEMPT_EXPIRY_MINUTES = 30
RECONCILE_BATCH_SIZE = 50


def _update_attempt_from_collection(
    attempt: PaymentAttempt,
    collection: LencoCollectionResult,
) -> None:
    """Record status, lenco_reference, fee, bearer, and settlementStatus from Lenco responses on the attempt."""
    attempt.status = collection.status
    if collection.lenco_reference is not None:
        attempt.lenco_reference = collection.lenco_reference
    if collection.fee_ngwee is not None:
        attempt.fee_ngwee = collection.fee_ngwee
    if collection.fee_bearer is not None:
        attempt.fee_bearer = collection.fee_bearer
    if collection.settlement_status is not None:
        attempt.settlement_status = collection.settlement_status
    attempt.updated_at = datetime.now(timezone.utc)


def settle_order_with_collection(
    db: Session,
    tenant_id: uuid.UUID,
    order: Order,
    collection: Optional[LencoCollectionResult],
    expected_status: Optional[str] = None,
    attempt: Optional[PaymentAttempt] = None,
) -> str:
    """
    Settle an order using verified provider collection data.
    Shared by the webhook handler, OTP submission, and the stuck-order reconciliation job/endpoint.
    Settlement never fails due to stock shortfall: drink stock is clamped at zero and orders.needs_review
    is flagged with a short reason if any shortfall occurred.
    """
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Collection not found at payment provider",
        )

    if expected_status and collection.status != expected_status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Collection status '{collection.status}' does not match event '{expected_status}'",
        )

    if collection.currency.upper() != "ZMW" or collection.amount_ngwee != order.total_ngwee:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Collection amount or currency does not match order",
        )

    if attempt is not None:
        _update_attempt_from_collection(attempt, collection)

    if order.payment_status == "paid":
        is_same_attempt = False
        if attempt is not None and attempt.reference == order.lenco_reference:
            is_same_attempt = True
        elif attempt is None and collection.reference == order.lenco_reference:
            is_same_attempt = True

        if collection.status == "successful" and not is_same_attempt:
            order.needs_review = True
            ref_str = attempt.reference if attempt is not None else collection.reference
            dup_reason = f"Duplicate payment on attempt {ref_str}: refund required"
            if order.review_reason:
                if dup_reason not in order.review_reason:
                    order.review_reason = f"{order.review_reason}; {dup_reason}"
            else:
                order.review_reason = dup_reason

            if attempt is not None:
                attempt.status = "successful"
                attempt.updated_at = datetime.now(timezone.utc)

            # Move any other active attempts older than PAYMENT_ATTEMPT_EXPIRY_MINUTES to 'expired'
            now_utc = datetime.now(timezone.utc)
            active_cutoff = now_utc - timedelta(minutes=PAYMENT_ATTEMPT_EXPIRY_MINUTES)
            other_active_attempts = (
                db.query(PaymentAttempt)
                .filter(
                    PaymentAttempt.tenant_id == tenant_id,
                    PaymentAttempt.order_id == order.id,
                    PaymentAttempt.id != (attempt.id if attempt else -1),
                    PaymentAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
                    PaymentAttempt.created_at <= active_cutoff,
                )
                .all()
            )
            for other_att in other_active_attempts:
                other_att.status = "expired"
                other_att.updated_at = now_utc

            db.commit()
            return "duplicate_paid"

        if attempt is not None:
            db.commit()
        return "already_paid"

    if collection.status == "successful":
        shortfall_reasons: List[str] = []
        for item in order.items:
            if item.menu_item and item.menu_item.category == "drink":
                reason = deduct_drink_stock_clamped_for_settlement(
                    db, tenant_id, item.menu_item, item.quantity
                )
                if reason:
                    shortfall_reasons.append(reason)

        if shortfall_reasons:
            order.needs_review = True
            order.review_reason = "; ".join(shortfall_reasons)

        order.payment_status = "paid"
        if attempt is not None:
            order.lenco_reference = attempt.reference

        # Move any other active attempts older than PAYMENT_ATTEMPT_EXPIRY_MINUTES to 'expired'
        now_utc = datetime.now(timezone.utc)
        active_cutoff = now_utc - timedelta(minutes=PAYMENT_ATTEMPT_EXPIRY_MINUTES)
        other_active_attempts = (
            db.query(PaymentAttempt)
            .filter(
                PaymentAttempt.tenant_id == tenant_id,
                PaymentAttempt.order_id == order.id,
                PaymentAttempt.id != (attempt.id if attempt else -1),
                PaymentAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
                PaymentAttempt.created_at <= active_cutoff,
            )
            .all()
        )
        for other_att in other_active_attempts:
            other_att.status = "expired"
            other_att.updated_at = now_utc

        db.commit()
        return "paid"

    if collection.status == "failed":
        if order.payment_status != "paid":
            other_active = (
                db.query(PaymentAttempt.id)
                .filter(
                    PaymentAttempt.tenant_id == tenant_id,
                    PaymentAttempt.order_id == order.id,
                    PaymentAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
                )
                .first()
            )
            if not other_active:
                order.payment_status = "failed"
        db.commit()
        return "failed"

    db.commit()
    return collection.status


@app.post("/api/payments/mobile-money/initiate", response_model=MobileMoneyInitiateResponse)
def initiate_mobile_money_payment(
    payload: MobileMoneyInitiateRequest,
    db: Session = Depends(get_tenant_db),
    _: User = Depends(get_current_user),
    lenco_client: LencoClient = Depends(get_lenco_client),
):
    tenant_id = db.info["tenant_id"]
    order = (
        db.query(Order)
        .filter(Order.id == payload.order_id, Order.tenant_id == tenant_id)
        .with_for_update()
        .first()
    )
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with id {payload.order_id} not found",
        )

    if order.payment_status == "paid":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order is already paid",
        )

    normalized_phone = normalize_zambian_phone(payload.phone)

    now = datetime.now(timezone.utc)
    expiry_cutoff = now - timedelta(minutes=PAYMENT_ATTEMPT_EXPIRY_MINUTES)

    # Check if an earlier attempt for this order is still active
    existing_attempts = (
        db.query(PaymentAttempt)
        .filter(
            PaymentAttempt.order_id == order.id,
            PaymentAttempt.tenant_id == tenant_id,
        )
        .order_by(PaymentAttempt.id.asc())
        .with_for_update()
        .all()
    )

    for prev_attempt in existing_attempts:
        if prev_attempt.status in ACTIVE_ATTEMPT_STATUSES:
            if prev_attempt.status == "initiating":
                if prev_attempt.created_at <= now - timedelta(minutes=2):
                    provider_col = lenco_client.get_collection_by_reference(
                        prev_attempt.reference
                    )
                    if provider_col is None:
                        prev_attempt.status = "failed"
                        prev_attempt.updated_at = now
                        db.commit()
                        continue
                    else:
                        _update_attempt_from_collection(prev_attempt, provider_col)
                        if provider_col.status == "successful":
                            settle_order_with_collection(
                                db=db,
                                tenant_id=tenant_id,
                                order=order,
                                collection=provider_col,
                                attempt=prev_attempt,
                            )
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Order has already been paid via an existing payment attempt",
                            )
                        if provider_col.status in ("failed", "expired"):
                            db.commit()
                            continue
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"An active payment attempt ({prev_attempt.reference}) is already in progress for this order",
                )

            provider_col = lenco_client.get_collection_by_reference(
                prev_attempt.reference
            )
            # Use attempt's own created_at only, never order.created_at
            is_past_expiry = prev_attempt.created_at <= expiry_cutoff

            if provider_col is not None:
                _update_attempt_from_collection(prev_attempt, provider_col)
                if provider_col.status == "successful":
                    settle_order_with_collection(
                        db=db,
                        tenant_id=tenant_id,
                        order=order,
                        collection=provider_col,
                        attempt=prev_attempt,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Order has already been paid via an existing payment attempt",
                    )
                if provider_col.status in ("failed", "expired"):
                    continue
                if is_past_expiry:
                    prev_attempt.status = "expired"
                    prev_attempt.updated_at = now
                    continue
            else:
                if is_past_expiry:
                    prev_attempt.status = "expired"
                    prev_attempt.updated_at = now
                    continue

            db.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An active payment attempt ({prev_attempt.reference}) is already in progress for this order",
            )

    # 1. Write-ahead attempt: insert PaymentAttempt with status 'initiating' and COMMIT before calling Lenco
    attempt_ref = str(uuid.uuid4())
    new_attempt = PaymentAttempt(
        tenant_id=tenant_id,
        order_id=order.id,
        reference=attempt_ref,
        lenco_reference=None,
        status="initiating",
        created_at=now,
        updated_at=now,
    )
    db.add(new_attempt)
    order.lenco_reference = attempt_ref
    if order.payment_status in ("failed", "expired"):
        order.payment_status = "pending"
    db.commit()
    db.refresh(new_attempt)

    try:
        collection = lenco_client.collect_mobile_money(
            reference=attempt_ref,
            phone=normalized_phone,
            operator=payload.operator,
            amount_ngwee=order.total_ngwee,
            currency="ZMW",
        )
    except HTTPException:
        raise
    except LencoRejectedError as exc:
        logger.warning(
            "Lenco collect_mobile_money rejected for ref=%s: %s",
            attempt_ref,
            exc,
        )
        bind_session_to_tenant(db, tenant_id)
        attempt_in_db = (
            db.query(PaymentAttempt)
            .filter(
                PaymentAttempt.id == new_attempt.id,
                PaymentAttempt.tenant_id == tenant_id,
            )
            .with_for_update()
            .first()
        )
        order_in_db = (
            db.query(Order)
            .filter(Order.id == order.id, Order.tenant_id == tenant_id)
            .with_for_update()
            .first()
        )
        if attempt_in_db is not None:
            attempt_in_db.status = "failed"
            attempt_in_db.updated_at = datetime.now(timezone.utc)
        if order_in_db is not None:
            order_in_db.payment_status = "failed"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc) or "Payment collection was rejected by provider",
        )
    except (LencoUnavailableError, Exception) as exc:
        logger.error(
            "Lenco collect_mobile_money unavailable for ref=%s: %s",
            attempt_ref,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider timed out or returned an error. Check payment status or wait for reconciliation instead of retrying blindly.",
        )

    # Re-fetch attempt and order under tenant session
    bind_session_to_tenant(db, tenant_id)
    attempt_in_db = (
        db.query(PaymentAttempt)
        .filter(PaymentAttempt.id == new_attempt.id, PaymentAttempt.tenant_id == tenant_id)
        .with_for_update()
        .first()
    )
    order_in_db = (
        db.query(Order)
        .filter(Order.id == order.id, Order.tenant_id == tenant_id)
        .with_for_update()
        .first()
    )
    if attempt_in_db is not None:
        _update_attempt_from_collection(attempt_in_db, collection)

    if collection.status == "successful":
        settle_order_with_collection(
            db=db,
            tenant_id=tenant_id,
            order=order_in_db or order,
            collection=collection,
            attempt=attempt_in_db,
        )
    elif collection.status == "failed":
        if order_in_db is not None:
            order_in_db.payment_status = "failed"
        db.commit()
    else:
        db.commit()

    return MobileMoneyInitiateResponse(
        status=collection.status,
        message=collection.message or "Mobile money prompt initiated",
        lenco_reference=attempt_ref,
        reference=attempt_ref,
        attempt_id=new_attempt.id,
        provider_reference=collection.lenco_reference,
    )


@app.post(
    "/api/payments/mobile-money/submit-otp",
    response_model=MobileMoneyInitiateResponse,
)
def submit_mobile_money_otp(
    payload: MobileMoneySubmitOtpRequest,
    db: Session = Depends(get_tenant_db),
    _: User = Depends(get_current_user),
    lenco_client: LencoClient = Depends(get_lenco_client),
):
    tenant_id = db.info["tenant_id"]
    order = (
        db.query(Order)
        .filter(Order.id == payload.order_id, Order.tenant_id == tenant_id)
        .with_for_update()
        .first()
    )
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with id {payload.order_id} not found",
        )

    cleaned_otp = (payload.otp or "").strip()
    if not cleaned_otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP is required",
        )

    attempt_query = db.query(PaymentAttempt).filter(
        PaymentAttempt.order_id == order.id,
        PaymentAttempt.tenant_id == tenant_id,
    )
    if payload.reference:
        attempt = (
            attempt_query.filter(PaymentAttempt.reference == payload.reference)
            .with_for_update()
            .first()
        )
    else:
        attempt = (
            attempt_query.order_by(PaymentAttempt.id.desc())
            .with_for_update()
            .first()
        )

    if not attempt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No payment attempt found for this order",
        )

    collection = lenco_client.submit_mobile_money_otp(
        reference=attempt.reference,
        otp=cleaned_otp,
        lenco_reference=attempt.lenco_reference,
    )

    _update_attempt_from_collection(attempt, collection)

    if collection.status == "successful":
        settle_order_with_collection(
            db=db,
            tenant_id=tenant_id,
            order=order,
            collection=collection,
            attempt=attempt,
        )
    elif collection.status == "failed":
        if order.payment_status != "paid":
            order.payment_status = "failed"
        db.commit()
    else:
        db.commit()

    return MobileMoneyInitiateResponse(
        status=collection.status,
        message=collection.message or "OTP submitted",
        lenco_reference=attempt.reference,
        reference=attempt.reference,
        attempt_id=attempt.id,
        provider_reference=attempt.lenco_reference,
    )


@app.post(
    "/api/payments/mobile-money/abandon",
    response_model=MobileMoneyAbandonResponse,
)
def abandon_mobile_money_payment(
    payload: MobileMoneyAbandonRequest,
    db: Session = Depends(get_tenant_db),
    _: User = Depends(get_current_user),
):
    """
    Marks a payment attempt 'abandoned' locally so a new attempt is allowed.
    Reconciliation continues to query abandoned attempts for 60 minutes so a late success
    is settled or flagged as a duplicate.
    """
    tenant_id = db.info["tenant_id"]
    order = (
        db.query(Order)
        .filter(Order.id == payload.order_id, Order.tenant_id == tenant_id)
        .with_for_update()
        .first()
    )
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with id {payload.order_id} not found",
        )

    attempt = (
        db.query(PaymentAttempt)
        .filter(
            PaymentAttempt.tenant_id == tenant_id,
            PaymentAttempt.order_id == order.id,
            PaymentAttempt.reference == payload.reference,
        )
        .with_for_update()
        .first()
    )
    if not attempt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment attempt with reference '{payload.reference}' not found",
        )

    if attempt.status == "successful":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot abandon a successful payment attempt",
        )

    attempt.status = "abandoned"
    attempt.updated_at = datetime.now(timezone.utc)
    db.commit()

    return MobileMoneyAbandonResponse(
        status="abandoned",
        order_id=order.id,
        reference=attempt.reference,
        message="Payment attempt abandoned locally. A new attempt can now be initiated.",
    )


@app.post("/api/webhooks/lenco")
async def lenco_webhook(
    request: Request,
    x_lenco_signature: Optional[str] = Header(None, alias="X-Lenco-Signature"),
    db: Session = Depends(get_db),
    lenco_client: LencoClient = Depends(get_lenco_client),
):
    # 1. Read raw request body bytes BEFORE any JSON parsing
    raw_body = await request.body()

    # 2. Verify HMAC-SHA512 signature keyed with sha256(LENCO_API_TOKEN).hexdigest()
    if not verify_lenco_webhook_signature(raw_body, x_lenco_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Lenco-Signature",
        )

    # 3. Parse JSON event only after signature verification
    try:
        payload: Dict[str, Any] = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON webhook payload",
        )

    event = payload.get("event")
    if event not in ("collection.successful", "collection.failed"):
        return {"status": "ignored", "event": event}

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    reference = (
        data.get("reference")
        or payload.get("reference")
        or payload.get("lenco_reference")
    )
    if not reference or not isinstance(reference, str):
        logger.warning("Lenco webhook missing reference for event=%s", event)
        return {"status": "ignored", "reason": "missing_reference"}

    # 4. Resolve tenant_id via narrow SECURITY DEFINER lookup (looks in payment_attempts then orders)
    tenant_id = db.execute(
        text("SELECT resolve_tenant_for_lenco_ref(:ref)"),
        {"ref": reference},
    ).scalar()
    if not tenant_id:
        logger.warning("Lenco webhook received for unknown reference=%s", reference)
        return {"status": "ignored", "reason": "unknown_reference"}

    # Set app.current_tenant and continue under normal RLS (bomapos_app has NOBYPASSRLS)
    bind_session_to_tenant(db, tenant_id)

    attempt = (
        db.query(PaymentAttempt)
        .filter(
            PaymentAttempt.tenant_id == tenant_id,
            (PaymentAttempt.reference == reference)
            | (PaymentAttempt.lenco_reference == reference),
        )
        .with_for_update()
        .first()
    )

    if attempt is not None:
        order = (
            db.query(Order)
            .filter(Order.id == attempt.order_id, Order.tenant_id == tenant_id)
            .with_for_update()
            .first()
        )
    else:
        order = (
            db.query(Order)
            .filter(
                Order.lenco_reference == reference,
                Order.tenant_id == tenant_id,
            )
            .with_for_update()
            .first()
        )

    if not order:
        logger.warning(
            "Lenco webhook order not found under tenant for reference=%s", reference
        )
        return {"status": "ignored", "reason": "unknown_reference"}

    expected_status = "successful" if event == "collection.successful" else "failed"

    # Idempotency check: replays are a no-op
    if order.payment_status == "paid":
        is_same_attempt = False
        if attempt is not None and attempt.reference == order.lenco_reference:
            is_same_attempt = True
        elif attempt is None and reference == order.lenco_reference:
            is_same_attempt = True

        if expected_status == "successful" and not is_same_attempt:
            # Duplicate payment detected on another attempt! Let settle_order_with_collection handle it.
            pass
        else:
            return {"status": "noop", "message": "Order already marked paid"}

    if (
        attempt is not None
        and attempt.status == "failed"
        and order.payment_status == "failed"
        and expected_status == "failed"
    ):
        return {"status": "noop", "message": "Order already marked failed"}

    # 5. Re-fetch collection from Lenco and verify status, amount, and currency match the order
    lookup_ref = attempt.reference if attempt is not None else reference
    collection = lenco_client.get_collection_by_reference(lookup_ref)
    outcome = settle_order_with_collection(
        db=db,
        tenant_id=tenant_id,
        order=order,
        collection=collection,
        expected_status=expected_status,
        attempt=attempt,
    )

    if outcome == "paid":
        return {
            "status": "success",
            "message": "Payment confirmed and drink stock updated",
            "needs_review": order.needs_review,
        }
    if outcome == "duplicate_paid":
        return {
            "status": "success",
            "message": "Duplicate payment recorded for review",
            "needs_review": order.needs_review,
        }
    if outcome == "failed":
        return {"status": "failed", "message": "Order marked as payment failed"}
    return {"status": outcome, "message": "No state transition required"}


def reconcile_tenant_pending_orders(
    db: Session,
    tenant_id: uuid.UUID,
    lenco_client: LencoClient,
    older_than_minutes: int = 10,
) -> ReconciliationResponse:
    """
    Reconcile payment attempts in `tenant_id` without holding FOR UPDATE row locks across Lenco HTTP calls:
      1. Read candidate attempts in batches of 50 without locking.
      2. Call Lenco (`get_collection_by_reference`) outside any row lock.
      3. Lock the single attempt & order rows with FOR UPDATE, re-check state, and settle or expire.
    Orders/attempts pending > 30 minutes and confirmed not-successful at Lenco become status='expired'.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=older_than_minutes)
    initiating_cutoff = now - timedelta(minutes=2)
    abandoned_cutoff = now - timedelta(minutes=60)
    expired_window_cutoff = now - timedelta(hours=48)
    expiry_cutoff = now - timedelta(minutes=PAYMENT_ATTEMPT_EXPIRY_MINUTES)

    checked = 0
    paid_count = 0
    failed_count = 0
    expired_count = 0
    pending_count = 0
    error_count = 0

    last_seen_id = 0
    while True:
        bind_session_to_tenant(db, tenant_id)
        candidates = (
            db.query(PaymentAttempt.id, PaymentAttempt.reference)
            .join(
                Order,
                (Order.id == PaymentAttempt.order_id)
                & (Order.tenant_id == PaymentAttempt.tenant_id),
            )
            .filter(
                PaymentAttempt.tenant_id == tenant_id,
                PaymentAttempt.id > last_seen_id,
                Order.payment_method == "mobile_money",
                or_(
                    and_(
                        PaymentAttempt.status == "initiating",
                        PaymentAttempt.created_at <= initiating_cutoff,
                    ),
                    and_(
                        PaymentAttempt.status.in_(("pending", "otp-required", "pay-offline")),
                        (PaymentAttempt.created_at <= cutoff) | (Order.created_at <= cutoff),
                    ),
                    and_(
                        PaymentAttempt.status == "expired",
                        PaymentAttempt.created_at >= expired_window_cutoff,
                    ),
                    and_(
                        PaymentAttempt.status == "abandoned",
                        PaymentAttempt.updated_at >= abandoned_cutoff,
                    ),
                ),
            )
            .order_by(PaymentAttempt.id.asc())
            .limit(RECONCILE_BATCH_SIZE)
            .all()
        )
        # End read transaction so no locks or snapshots are held during Lenco HTTP requests
        db.commit()

        if not candidates:
            break

        for attempt_id, attempt_ref in candidates:
            last_seen_id = max(last_seen_id, attempt_id)
            checked += 1

            # 2. Call Lenco outside any database row lock with failure isolation
            try:
                collection = lenco_client.get_collection_by_reference(attempt_ref)
            except RuntimeError as exc:
                logger.warning(
                    "Reconciliation query failed for attempt_ref=%s: %s",
                    attempt_ref,
                    exc.__class__.__name__,
                )
                pending_count += 1
                error_count += 1
                continue

            # 3. Lock the single attempt + order row, re-check state, and settle or expire
            bind_session_to_tenant(db, tenant_id)
            locked_attempt = (
                db.query(PaymentAttempt)
                .filter(
                    PaymentAttempt.id == attempt_id,
                    PaymentAttempt.tenant_id == tenant_id,
                )
                .with_for_update()
                .first()
            )
            if not locked_attempt:
                db.commit()
                continue

            locked_order = (
                db.query(Order)
                .filter(
                    Order.id == locked_attempt.order_id,
                    Order.tenant_id == tenant_id,
                )
                .with_for_update()
                .first()
            )
            if not locked_order:
                db.commit()
                continue

            # Special case for 'initiating': older than 2 minutes
            if locked_attempt.status == "initiating":
                if collection is None:
                    locked_attempt.status = "failed"
                    locked_attempt.updated_at = datetime.now(timezone.utc)
                    other_active = (
                        db.query(PaymentAttempt.id)
                        .filter(
                            PaymentAttempt.tenant_id == tenant_id,
                            PaymentAttempt.order_id == locked_order.id,
                            PaymentAttempt.id != locked_attempt.id,
                            PaymentAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
                        )
                        .first()
                    )
                    if not other_active and locked_order.payment_status != "paid":
                        locked_order.payment_status = "failed"
                    db.commit()
                    failed_count += 1
                    continue
                else:
                    _update_attempt_from_collection(locked_attempt, collection)
                    if collection.status in ("successful", "failed"):
                        try:
                            outcome = settle_order_with_collection(
                                db=db,
                                tenant_id=tenant_id,
                                order=locked_order,
                                collection=collection,
                                attempt=locked_attempt,
                            )
                            if outcome in ("paid", "duplicate_paid"):
                                paid_count += 1
                            elif outcome == "failed":
                                failed_count += 1
                            else:
                                pending_count += 1
                        except HTTPException as exc:
                            db.rollback()
                            logger.warning(
                                "Reconciliation skipped order_id=%s ref=%s: %s",
                                locked_order.id,
                                attempt_ref,
                                exc.detail,
                            )
                            pending_count += 1
                    else:
                        db.commit()
                        pending_count += 1
                    continue

            # If order is already paid, check if this attempt is a duplicate success
            if locked_order.payment_status == "paid":
                if (
                    collection is not None
                    and collection.status == "successful"
                    and locked_attempt.status != "successful"
                ):
                    try:
                        outcome = settle_order_with_collection(
                            db=db,
                            tenant_id=tenant_id,
                            order=locked_order,
                            collection=collection,
                            attempt=locked_attempt,
                        )
                        if outcome in ("paid", "duplicate_paid"):
                            paid_count += 1
                        else:
                            pending_count += 1
                    except HTTPException as exc:
                        db.rollback()
                        logger.warning(
                            "Reconciliation skipped duplicate order_id=%s ref=%s: %s",
                            locked_order.id,
                            attempt_ref,
                            exc.detail,
                        )
                        pending_count += 1
                else:
                    db.commit()
                continue

            # If attempt is 'abandoned':
            if locked_attempt.status == "abandoned":
                if collection is not None and collection.status == "successful":
                    try:
                        outcome = settle_order_with_collection(
                            db=db,
                            tenant_id=tenant_id,
                            order=locked_order,
                            collection=collection,
                            attempt=locked_attempt,
                        )
                        if outcome in ("paid", "duplicate_paid"):
                            paid_count += 1
                        else:
                            pending_count += 1
                    except HTTPException as exc:
                        db.rollback()
                        logger.warning(
                            "Reconciliation skipped abandoned order_id=%s ref=%s: %s",
                            locked_order.id,
                            attempt_ref,
                            exc.detail,
                        )
                        pending_count += 1
                else:
                    db.commit()
                continue

            # If already expired and still not successful at Lenco, nothing further to transition
            if locked_attempt.status == "expired" and (
                collection is None or collection.status != "successful"
            ):
                db.commit()
                continue

            if locked_attempt.status not in (*ACTIVE_ATTEMPT_STATUSES, "expired"):
                db.commit()
                continue

            # Expiry check using attempt's own created_at only!
            is_expired_by_age = locked_attempt.created_at <= expiry_cutoff

            if collection is not None and collection.status in ("successful", "failed"):
                try:
                    outcome = settle_order_with_collection(
                        db=db,
                        tenant_id=tenant_id,
                        order=locked_order,
                        collection=collection,
                        attempt=locked_attempt,
                    )
                    if outcome in ("paid", "duplicate_paid"):
                        paid_count += 1
                    elif outcome == "failed":
                        failed_count += 1
                    else:
                        pending_count += 1
                except HTTPException as exc:
                    db.rollback()
                    logger.warning(
                        "Reconciliation skipped order_id=%s ref=%s due to verification mismatch: %s",
                        locked_order.id,
                        attempt_ref,
                        exc.detail,
                    )
                    pending_count += 1
                continue

            # Confirmed not-successful at Lenco (collection is None or still pending/pay-offline/otp-required)
            if collection is not None:
                _update_attempt_from_collection(locked_attempt, collection)

            if is_expired_by_age:
                locked_attempt.status = "expired"
                locked_attempt.updated_at = datetime.now(timezone.utc)
                other_active = (
                    db.query(PaymentAttempt.id)
                    .filter(
                        PaymentAttempt.tenant_id == tenant_id,
                        PaymentAttempt.order_id == locked_order.id,
                        PaymentAttempt.id != locked_attempt.id,
                        PaymentAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
                    )
                    .first()
                )
                if not other_active and locked_order.payment_status == "pending":
                    locked_order.payment_status = "expired"
                db.commit()
                expired_count += 1
            else:
                db.commit()
                pending_count += 1

    return ReconciliationResponse(
        checked_count=checked,
        settled_paid_count=paid_count,
        settled_failed_count=failed_count,
        expired_count=expired_count,
        still_pending_count=pending_count,
        error_count=error_count,
    )


def reconcile_all_tenants_stuck_orders(
    older_than_minutes: int = 10,
    lenco_client: Optional[LencoClient] = None,
) -> Dict[str, ReconciliationResponse]:
    """Background/cron job entry point to reconcile stuck mobile money orders across all active tenants under RLS."""
    client_impl = lenco_client or get_lenco_client()
    results: Dict[str, ReconciliationResponse] = {}
    db = SessionLocal()
    try:
        active_tenants = db.query(Tenant).filter(Tenant.status == "active").all()
        for tenant in active_tenants:
            try:
                results[tenant.slug] = reconcile_tenant_pending_orders(
                    db=db,
                    tenant_id=tenant.id,
                    lenco_client=client_impl,
                    older_than_minutes=older_than_minutes,
                )
            except Exception as exc:
                logger.error(
                    "Tenant reconciliation failed for tenant_slug=%s: %s",
                    tenant.slug,
                    exc.__class__.__name__,
                )
                results[tenant.slug] = ReconciliationResponse(
                    checked_count=0,
                    settled_paid_count=0,
                    settled_failed_count=0,
                    expired_count=0,
                    still_pending_count=0,
                    error_count=1,
                )
        return results
    finally:
        db.close()


@app.post("/internal/reconcile", response_model=Dict[str, ReconciliationResponse])
def internal_reconcile_cron(
    older_than_minutes: int = Query(5, ge=0),
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
    lenco_client: LencoClient = Depends(get_lenco_client),
):
    """
    Internal cron endpoint meant to be invoked every 5 minutes by the host scheduler.
    Protected by X-Cron-Secret header matching CRON_SECRET env var.
    """
    expected_secret = get_cron_secret()
    if (
        not expected_secret
        or not x_cron_secret
        or not hmac.compare_digest(expected_secret, x_cron_secret.strip())
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Cron-Secret header",
        )
    return reconcile_all_tenants_stuck_orders(
        older_than_minutes=older_than_minutes,
        lenco_client=lenco_client,
    )


@app.post("/api/payments/reconcile", response_model=ReconciliationResponse)
def reconcile_pending_payments(
    older_than_minutes: int = Query(10, ge=0),
    db: Session = Depends(get_tenant_db),
    _: User = Depends(require_owner),
    lenco_client: LencoClient = Depends(get_lenco_client),
):
    tenant_id = db.info["tenant_id"]
    return reconcile_tenant_pending_orders(
        db=db,
        tenant_id=tenant_id,
        lenco_client=lenco_client,
        older_than_minutes=older_than_minutes,
    )


@app.get("/api/payments/status/{lenco_reference}", response_model=PaymentStatusResponse)
def get_payment_status(
    lenco_reference: str,
    db: Session = Depends(get_tenant_db),
    _: User = Depends(get_current_user),
):
    tenant_id = db.info["tenant_id"]
    attempt = (
        db.query(PaymentAttempt)
        .filter(
            PaymentAttempt.tenant_id == tenant_id,
            (PaymentAttempt.reference == lenco_reference)
            | (PaymentAttempt.lenco_reference == lenco_reference),
        )
        .order_by(PaymentAttempt.id.desc())
        .first()
    )

    if attempt is not None:
        order = (
            db.query(Order)
            .filter(Order.id == attempt.order_id, Order.tenant_id == tenant_id)
            .first()
        )
    else:
        order = (
            db.query(Order)
            .filter(
                Order.lenco_reference == lenco_reference,
                Order.tenant_id == tenant_id,
            )
            .first()
        )

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with lenco_reference '{lenco_reference}' not found",
        )

    distinct_status = (
        attempt.status
        if attempt is not None
        else ("successful" if order.payment_status == "paid" else order.payment_status)
    )
    if order.payment_status == "paid":
        distinct_status = "successful"

    return PaymentStatusResponse(
        order_id=order.id,
        payment_status=order.payment_status,
        status=distinct_status,
        lenco_reference=attempt.reference if attempt is not None else order.lenco_reference,
        needs_review=bool(order.needs_review),
        review_reason=order.review_reason,
    )


# ---------------------------------------------------------
# 6. Owner Dashboards, Settlement & Analytics (FR-5.1 - FR-5.3)
# ---------------------------------------------------------
@app.get("/api/dashboard/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    db: Session = Depends(get_tenant_db),
    _: User = Depends(require_owner),
):
    tenant_id = db.info["tenant_id"]
    today_lusaka = datetime.now(LUSAKA_TZ).date()
    lusaka_order_date = cast(func.timezone(BUSINESS_TIMEZONE, Order.created_at), Date)

    today_row = (
        db.query(
            func.coalesce(func.sum(Order.total_ngwee), 0).label("total_ngwee"),
            func.coalesce(
                func.sum(
                    case(
                        (Order.payment_method == "cash", Order.total_ngwee),
                        else_=0,
                    )
                ),
                0,
            ).label("cash_ngwee"),
            func.count(Order.id).label("orders_count"),
        )
        .filter(
            Order.tenant_id == tenant_id,
            Order.payment_status == "paid",
            lusaka_order_date == today_lusaka,
        )
        .one()
    )

    settlement_ngwee = (
        db.query(func.coalesce(func.sum(Order.total_ngwee), 0))
        .filter(
            Order.tenant_id == tenant_id,
            Order.payment_status == "paid",
            Order.payment_method == "mobile_money",
        )
        .scalar()
        or 0
    )

    low_stock_records = (
        db.query(DrinkInventory)
        .join(
            MenuItem,
            (MenuItem.id == DrinkInventory.menu_item_id)
            & (MenuItem.tenant_id == DrinkInventory.tenant_id),
        )
        .filter(
            DrinkInventory.tenant_id == tenant_id,
            DrinkInventory.stock_quantity <= DrinkInventory.low_stock_threshold,
        )
        .all()
    )

    low_stock_alerts = [
        DrinkInventoryWithItemResponse.model_validate(inv) for inv in low_stock_records
    ]

    needs_review_records = (
        db.query(Order)
        .filter(
            Order.tenant_id == tenant_id,
            Order.needs_review.is_(True),
        )
        .order_by(Order.created_at.desc())
        .all()
    )
    needs_review_orders = [
        OrderResponse.model_validate(o) for o in needs_review_records
    ]

    return DashboardSummaryResponse(
        today_total_revenue_ngwee=int(today_row.total_ngwee),
        today_cash_revenue_ngwee=int(today_row.cash_ngwee),
        settlement_account_balance_ngwee=int(settlement_ngwee),
        today_orders_count=int(today_row.orders_count),
        low_stock_alerts=low_stock_alerts,
        needs_review_count=len(needs_review_orders),
        needs_review_orders=needs_review_orders,
    )


@app.get("/api/dashboard/calendar", response_model=List[CalendarDayAnalytics])
def get_dashboard_calendar(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2020, le=2099),
    db: Session = Depends(get_tenant_db),
    _: User = Depends(require_owner),
):
    tenant_id = db.info["tenant_id"]
    lusaka_ts = func.timezone(BUSINESS_TIMEZONE, Order.created_at)
    lusaka_day = cast(lusaka_ts, Date)

    filters = [
        Order.tenant_id == tenant_id,
        Order.payment_status == "paid",
    ]
    if year is not None:
        filters.append(extract("year", lusaka_ts) == year)
    if month is not None:
        filters.append(extract("month", lusaka_ts) == month)

    meals_subq = (
        db.query(
            OrderItem.order_id.label("order_id"),
            func.coalesce(
                func.sum(
                    case(
                        (MenuItem.category == "meal", OrderItem.quantity),
                        else_=0,
                    )
                ),
                0,
            ).label("meals_sold"),
        )
        .join(
            MenuItem,
            (MenuItem.id == OrderItem.menu_item_id)
            & (MenuItem.tenant_id == OrderItem.tenant_id),
        )
        .filter(OrderItem.tenant_id == tenant_id)
        .group_by(OrderItem.order_id)
        .subquery()
    )

    rows = (
        db.query(
            lusaka_day.label("day"),
            func.coalesce(func.sum(Order.total_ngwee), 0).label("total_revenue_ngwee"),
            func.count(Order.id).label("total_orders_count"),
            func.coalesce(func.sum(func.coalesce(meals_subq.c.meals_sold, 0)), 0).label(
                "total_meals_sold"
            ),
        )
        .outerjoin(meals_subq, meals_subq.c.order_id == Order.id)
        .filter(*filters)
        .group_by(lusaka_day)
        .order_by(lusaka_day.asc())
        .all()
    )

    return [
        CalendarDayAnalytics(
            date=row.day.strftime("%Y-%m-%d"),
            total_revenue_ngwee=int(row.total_revenue_ngwee),
            total_orders_count=int(row.total_orders_count),
            total_meals_sold=int(row.total_meals_sold),
        )
        for row in rows
    ]
