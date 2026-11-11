"""add payment_attempts table with RLS and order needs_review columns

Revision ID: 0005_payment_attempts_review
Revises: 0004_lenco_ref_unique
Create Date: 2026-11-11 12:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005_payment_attempts_review"
down_revision: Union[str, Sequence[str], None] = "0004_lenco_ref_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "needs_review",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("review_reason", sa.String(), nullable=True),
    )

    op.create_table(
        "payment_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(), nullable=False),
        sa.Column("lenco_reference", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("fee_ngwee", sa.BigInteger(), nullable=True),
        sa.Column("fee_bearer", sa.String(), nullable=True),
        sa.Column("settlement_status", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            name="fk_payment_attempts_order_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_payment_attempts_id"), "payment_attempts", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_payment_attempts_tenant_id"),
        "payment_attempts",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payment_attempts_order_id"),
        "payment_attempts",
        ["order_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payment_attempts_reference"),
        "payment_attempts",
        ["reference"],
        unique=True,
    )
    op.create_index(
        op.f("ix_payment_attempts_lenco_reference"),
        "payment_attempts",
        ["lenco_reference"],
        unique=False,
    )

    # Enable & Force Row Level Security on payment_attempts
    op.execute(sa.text("ALTER TABLE payment_attempts ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE payment_attempts FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            "CREATE POLICY tenant_isolation_policy ON payment_attempts "
            "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
        )
    )

    op.execute(
        sa.text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE payment_attempts TO bomapos_app"
        )
    )
    op.execute(
        sa.text(
            "GRANT USAGE, SELECT ON SEQUENCE payment_attempts_id_seq TO bomapos_app"
        )
    )

    # Update resolve_tenant_for_lenco_ref to look in payment_attempts (with fallback to orders)
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
                SELECT COALESCE(
                    (
                        SELECT tenant_id
                        FROM payment_attempts
                        WHERE reference = p_lenco_ref OR lenco_reference = p_lenco_ref
                        ORDER BY id DESC
                        LIMIT 1
                    ),
                    (
                        SELECT tenant_id
                        FROM orders
                        WHERE lenco_reference = p_lenco_ref
                        LIMIT 1
                    )
                );
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            "GRANT EXECUTE ON FUNCTION resolve_tenant_for_lenco_ref(text) TO bomapos_app"
        )
    )


def downgrade() -> None:
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
    op.execute(
        sa.text(
            "GRANT EXECUTE ON FUNCTION resolve_tenant_for_lenco_ref(text) TO bomapos_app"
        )
    )

    op.execute(
        sa.text("DROP POLICY IF EXISTS tenant_isolation_policy ON payment_attempts")
    )
    op.execute(sa.text("ALTER TABLE payment_attempts NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE payment_attempts DISABLE ROW LEVEL SECURITY"))

    op.drop_index(
        op.f("ix_payment_attempts_lenco_reference"), table_name="payment_attempts"
    )
    op.drop_index(op.f("ix_payment_attempts_reference"), table_name="payment_attempts")
    op.drop_index(op.f("ix_payment_attempts_order_id"), table_name="payment_attempts")
    op.drop_index(op.f("ix_payment_attempts_tenant_id"), table_name="payment_attempts")
    op.drop_index(op.f("ix_payment_attempts_id"), table_name="payment_attempts")
    op.drop_table("payment_attempts")

    op.drop_column("orders", "review_reason")
    op.drop_column("orders", "needs_review")

