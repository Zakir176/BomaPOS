import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session, with_loader_criteria

load_dotenv()


def _normalize_pg_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL")
if not SQLALCHEMY_DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

SQLALCHEMY_DATABASE_URL = _normalize_pg_url(SQLALCHEMY_DATABASE_URL)

ADMIN_DATABASE_URL = _normalize_pg_url(
    os.environ.get("ADMIN_DATABASE_URL", SQLALCHEMY_DATABASE_URL)
)

engine = create_engine(SQLALCHEMY_DATABASE_URL)
admin_engine = create_engine(ADMIN_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
AdminSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=admin_engine)

Base = declarative_base()


@event.listens_for(Session, "after_begin")
def _set_rls_tenant_on_begin(session: Session, transaction, connection):
    """Ensure every transaction on a tenant-bound session sets app.current_tenant for Postgres RLS."""
    tenant_id = session.info.get("tenant_id")
    if tenant_id is not None:
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tid, true)"),
            {"tid": str(tenant_id)},
        )


@event.listens_for(Session, "do_orm_execute")
def _enforce_tenant_criteria(execute_state):
    """Automatically scope all ORM SELECT/UPDATE/DELETE statements on tenant-owned models to session.info['tenant_id']."""
    tenant_id = execute_state.session.info.get("tenant_id")
    if tenant_id is None:
        return

    if execute_state.is_select or execute_state.is_update or execute_state.is_delete:
        try:
            from .models import User, RefreshToken, MenuItem, DrinkInventory, Order, OrderItem
        except ImportError:
            from models import User, RefreshToken, MenuItem, DrinkInventory, Order, OrderItem

        for model_cls in (User, RefreshToken, MenuItem, DrinkInventory, Order, OrderItem):
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    model_cls,
                    model_cls.tenant_id == tenant_id,
                    include_aliases=True,
                )
            )


def bind_session_to_tenant(db: Session, tenant_id) -> Session:
    """Bind a SQLAlchemy session to a specific tenant and configure Postgres RLS for the active transaction."""
    db.info["tenant_id"] = tenant_id
    db.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": str(tenant_id)},
    )
    return db


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
