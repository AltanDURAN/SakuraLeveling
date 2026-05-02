"""add equipment_slot and two_hand_flag to items + migrate slot names

Revision ID: 559b131677cb
Revises: 84b66f305f4b
Create Date: 2026-05-02 05:30:16.846738

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '559b131677cb'
down_revision: Union[str, Sequence[str], None] = '84b66f305f4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Migration des anciens slot codes vers les nouveaux (français, slot anatomique)
_LEGACY_SLOT_MAPPING = {
    "weapon": "main_droite",
    "helmet": "casque",
    "chest": "plastron",
    "boots": "bottes",
    "ring_1": "bague",
    "ring_2": "bracelet",
}


def upgrade() -> None:
    op.add_column(
        "item_definitions",
        sa.Column("equipment_slot", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "item_definitions",
        sa.Column(
            "requires_two_hands",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # Migration des player_equipment.slot vers les nouveaux noms anatomiques.
    # Exécuté avec UPDATE direct pour préserver les équipements existants.
    for legacy, new in _LEGACY_SLOT_MAPPING.items():
        op.execute(
            sa.text(
                "UPDATE player_equipment SET slot = :new WHERE slot = :legacy"
            ).bindparams(legacy=legacy, new=new)
        )


def downgrade() -> None:
    # Reverse mapping (best-effort, perd l'info pour les nouveaux slots
    # qui n'avaient pas d'équivalent legacy).
    for legacy, new in _LEGACY_SLOT_MAPPING.items():
        op.execute(
            sa.text(
                "UPDATE player_equipment SET slot = :legacy WHERE slot = :new"
            ).bindparams(legacy=legacy, new=new)
        )

    op.drop_column("item_definitions", "requires_two_hands")
    op.drop_column("item_definitions", "equipment_slot")
