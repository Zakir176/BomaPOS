"""add tenant_id, composite constraints, and RLS with security_definer resolvers

Revision ID: 0002_multi_tenant_rls
Revises: 0001_initial
Create Date: 2026-11-10 15:30:00.000000

Migration & Role Setup Notes:
-----------------------------
1. Non-superuser / Non-owner Application Role (`bomapos_app`):
   PostgreSQL superusers and roles with `BYPASSRLS` bypass Row Level Security.
   Table owners also bypass RLS unless `FORCE ROW LEVEL SECURITY` is enabled.
   This migration provisions a dedicated non-superuser, non-owner role
   `bomapos_app` (`NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`) and grants
   it `SELECT, INSERT, UPDATE, DELETE` on all tables and `USAGE, SELECT` on all
   sequences in `public`.
   In runtime (`DATABASE_URL`), the application connects as `bomapos_app`, while
   migrations run via `ADMIN_DATABASE_URL` (schema owner `postgres`).

2. Per-Transaction Tenant Context & RLS Policies:
   Every tenant-owned table (`users`, `menu_items`, `drink_inventories`,
   `orders`, `order_items`) has `ENABLE ROW LEVEL SECURITY` and
   `FORCE ROW LEVEL SECURITY` with policy:
     `tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid`
   The request-scoped database dependency executes:
     `SELECT set_config('app.current_tenant', :tenant_id, true)`
   at the start of each transaction so RLS enforces tenant isolation at the
   database engine level in addition to SQLAlchemy ORM query scoping.

3. Temporary Bootstrap Resolvers (until Prompt 3 auth lands):
   Because `users` and `orders` have `FORCE ROW LEVEL SECURITY`, resolving the
   tenant from a legacy token (`user_id:role:username`) or Lenco webhook
   reference (`lenco_reference`) prior to setting `app.current_tenant` uses
   narrow `SECURITY DEFINER` lookup functions (`resolve_tenant_for_user`,
   `resolve_tenant_for_login`, `resolve_tenant_for_lenco_ref`) that return ONLY
   the `UUID` `tenant_id`.
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_multi_tenant_rls"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_TABLES = [
    "users",
    "menu_items",
    "drink_inventories",
    "orders",
    "order_items",
]


def upgrade() -> None:
    # 1. Create tenants table
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column(
            "timezone", sa.String(), server_default="Africa/Lusaka", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended')", name="ck_tenants_status"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tenants_id"), "tenants", ["id"], unique=False)
    op.create_index(op.f("ix_tenants_slug"), "tenants", ["slug"], unique=True)

    # Insert a default tenant if any rows already exist prior to migration
    default_tenant_id = str(uuid.uuid4())
    op.execute(
        sa.text(
            f"INSERT INTO tenants (id, name, slug, status, timezone) "
            f"SELECT '{default_tenant_id}'::uuid, 'Default Tenant', 'default', 'active', 'Africa/Lusaka' "
            f"WHERE EXISTS (SELECT 1 FROM users LIMIT 1) OR EXISTS (SELECT 1 FROM menu_items LIMIT 1)"
        )
    )

    # 2. Add tenant_id to all tenant-owned tables (nullable first for backfill, then NOT NULL + FK + index)
    for table in TENANT_TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=True))
        op.execute(
            sa.text(
                f"UPDATE {table} SET tenant_id = '{default_tenant_id}'::uuid WHERE tenant_id IS NULL"
            )
        )
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_index(op.f(f"ix_{table}_tenant_id"), table, ["tenant_id"], unique=False)
        op.create_foreign_key(
            f"fk_{table}_tenant_id_tenants", table, "tenants", ["tenant_id"], ["id"]
        )

    # 3. Replace global uniqueness with per-tenant uniqueness
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=False)
    op.create_unique_constraint(
        "uq_users_tenant_username", "users", ["tenant_id", "username"]
    )

    op.drop_index(op.f("ix_menu_items_name"), table_name="menu_items")
    op.create_index(op.f("ix_menu_items_name"), "menu_items", ["name"], unique=False)
    op.create_unique_constraint(
        "uq_menu_items_tenant_name", "menu_items", ["tenant_id", "name"]
    )

    # 4. Composite uniqueness on (id, tenant_id) + composite FKs preventing cross-tenant references
    op.create_unique_constraint("uq_users_id_tenant", "users", ["id", "tenant_id"])
    op.create_unique_constraint(
        "uq_menu_items_id_tenant", "menu_items", ["id", "tenant_id"]
    )
    op.create_unique_constraint("uq_orders_id_tenant", "orders", ["id", "tenant_id"])

    op.create_foreign_key(
        "fk_drink_inventories_menu_item_tenant",
        "drink_inventories",
        "menu_items",
        ["menu_item_id", "tenant_id"],
        ["id", "tenant_id"],
    )
    op.create_foreign_key(
        "fk_orders_cashier_tenant",
        "orders",
        "users",
        ["cashier_id", "tenant_id"],
        ["id", "tenant_id"],
    )
    op.create_foreign_key(
        "fk_order_items_order_tenant",
        "order_items",
        "orders",
        ["order_id", "tenant_id"],
        ["id", "tenant_id"],
    )
    op.create_foreign_key(
        "fk_order_items_menu_item_tenant",
        "order_items",
        "menu_items",
        ["menu_item_id", "tenant_id"],
        ["id", "tenant_id"],
    )

    # 5. Enable & Force Row Level Security on every tenant-owned table
    for table in TENANT_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                f"CREATE POLICY tenant_isolation_policy ON {table} "
                f"USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid) "
                f"WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
            )
        )

    # 6. Create narrow SECURITY DEFINER tenant-resolution helpers for pre-RLS bootstrap
    # TEMPORARY: Used until Prompt 3 embeds tenant_id in the verified auth token.
    # Because `users` and `orders` have FORCE ROW LEVEL SECURITY, even the table owner is subject
    # to RLS unless row_security = off is set inside the trusted SECURITY DEFINER resolver.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION resolve_tenant_for_user(p_user_id integer)
            RETURNS uuid
            LANGUAGE sql
            SECURITY DEFINER
            SET search_path = public
            SET row_security = off
            AS $$
                SELECT tenant_id FROM users WHERE id = p_user_id LIMIT 1;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION resolve_tenant_for_login(p_username text, p_tenant_slug text DEFAULT NULL)
            RETURNS uuid
            LANGUAGE sql
            SECURITY DEFINER
            SET search_path = public
            SET row_security = off
            AS $$
                SELECT u.tenant_id
                FROM users u
                JOIN tenants t ON t.id = u.tenant_id
                WHERE u.username = p_username
                  AND (p_tenant_slug IS NULL OR t.slug = p_tenant_slug)
                ORDER BY u.id ASC
                LIMIT 1;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION resolve_tenant_for_lenco_ref(p_lenco_ref text)
            RETURNS uuid
            LANGUAGE sql
            SECURITY DEFINER
            SET search_path = public
            SET row_security = off
            AS $$
                SELECT tenant_id FROM orders WHERE lenco_reference = p_lenco_ref LIMIT 1;
            $$;
            """
        )
    )

    # 7. Provision non-superuser, non-owner application role `bomapos_app`
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bomapos_app') THEN
                    CREATE ROLE bomapos_app WITH LOGIN PASSWORD 'bomapos_app' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
                END IF;
            END
            $$;
            """
        )
    )
    op.execute(sa.text("GRANT USAGE ON SCHEMA public TO bomapos_app"))
    op.execute(
        sa.text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO bomapos_app"
        )
    )
    op.execute(
        sa.text(
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO bomapos_app"
        )
    )
    op.execute(
        sa.text(
            "GRANT EXECUTE ON FUNCTION resolve_tenant_for_user(integer), resolve_tenant_for_login(text, text), resolve_tenant_for_lenco_ref(text) TO bomapos_app"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP FUNCTION IF EXISTS resolve_tenant_for_lenco_ref(text)"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS resolve_tenant_for_login(text, text)"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS resolve_tenant_for_user(integer)"))

    for table in TENANT_TABLES:
        op.execute(
            sa.text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table}")
        )
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))

    op.drop_constraint(
        "fk_order_items_menu_item_tenant", "order_items", type_="foreignkey"
    )
    op.drop_constraint("fk_order_items_order_tenant", "order_items", type_="foreignkey")
    op.drop_constraint("fk_orders_cashier_tenant", "orders", type_="foreignkey")
    op.drop_constraint(
        "fk_drink_inventories_menu_item_tenant",
        "drink_inventories",
        type_="foreignkey",
    )

    op.drop_constraint("uq_orders_id_tenant", "orders", type_="unique")
    op.drop_constraint("uq_menu_items_id_tenant", "menu_items", type_="unique")
    op.drop_constraint("uq_users_id_tenant", "users", type_="unique")

    op.drop_constraint("uq_menu_items_tenant_name", "menu_items", type_="unique")
    op.drop_index(op.f("ix_menu_items_name"), table_name="menu_items")
    op.create_index(op.f("ix_menu_items_name"), "menu_items", ["name"], unique=True)

    op.drop_constraint("uq_users_tenant_username", "users", type_="unique")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    for table in reversed(TENANT_TABLES):
        op.drop_constraint(
            f"fk_{table}_tenant_id_tenants", table, type_="foreignkey"
        )
        op.drop_index(op.f(f"ix_{table}_tenant_id"), table_name=table)
        op.drop_column(table, "tenant_id")

    op.drop_index(op.f("ix_tenants_slug"), table_name="tenants")
    op.drop_index(op.f("ix_tenants_id"), table_name="tenants")
    op.drop_table("tenants")
