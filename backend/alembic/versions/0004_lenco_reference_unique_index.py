"""add unique index on orders.lenco_reference

Revision ID: 0004_lenco_ref_unique
Revises: 0003_jwt_refresh_tokens
Create Date: 2026-11-10 16:27:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_lenco_ref_unique"
down_revision: Union[str, Sequence[str], None] = "0003_jwt_refresh_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_orders_lenco_reference"),
        "orders",
        ["lenco_reference"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_orders_lenco_reference"), table_name="orders")

