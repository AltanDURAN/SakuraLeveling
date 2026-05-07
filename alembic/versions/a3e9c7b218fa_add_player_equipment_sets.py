"""add player equipment sets (loadouts)

Revision ID: a3e9c7b218fa
Revises: 277fe14515ad
Create Date: 2026-05-07 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3e9c7b218fa"
down_revision: Union[str, Sequence[str], None] = "277fe14515ad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "player_equipment_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "player_id", sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "player_id", "name", name="uq_player_set_name",
        ),
    )
    op.create_index(
        "ix_player_equipment_sets_player_id",
        "player_equipment_sets", ["player_id"],
    )

    op.create_table(
        "player_equipment_set_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "equipment_set_id", sa.Integer(),
            sa.ForeignKey(
                "player_equipment_sets.id", ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("slot", sa.String(length=50), nullable=False),
        sa.Column(
            "item_definition_id", sa.Integer(),
            sa.ForeignKey("item_definitions.id"), nullable=False,
        ),
        sa.UniqueConstraint(
            "equipment_set_id", "slot", name="uq_set_slot",
        ),
    )
    op.create_index(
        "ix_player_equipment_set_items_set_id",
        "player_equipment_set_items", ["equipment_set_id"],
    )
    op.create_index(
        "ix_player_equipment_set_items_item_id",
        "player_equipment_set_items", ["item_definition_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_player_equipment_set_items_item_id",
        "player_equipment_set_items",
    )
    op.drop_index(
        "ix_player_equipment_set_items_set_id",
        "player_equipment_set_items",
    )
    op.drop_table("player_equipment_set_items")
    op.drop_index(
        "ix_player_equipment_sets_player_id",
        "player_equipment_sets",
    )
    op.drop_table("player_equipment_sets")
