"""add family to item_definitions

Revision ID: 277fe14515ad
Revises: 9f6c9ab82525
Create Date: 2026-05-07 07:53:07.284555

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '277fe14515ad'
down_revision: Union[str, Sequence[str], None] = '9f6c9ab82525'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "item_definitions",
        sa.Column("family", sa.String(length=50), nullable=False, server_default=""),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("item_definitions", "family")
