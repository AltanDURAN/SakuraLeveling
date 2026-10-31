"""Index des tenues : mêmes noms partout.

La base de production avait les index de `player_equipment_set_items` sous
les noms automatiques de `index=True` (`..._equipment_set_id`,
`..._item_definition_id`), une base migrée de zéro sous ceux de
a3e9c7b218fa (`..._set_id`, `..._item_id`). Mêmes colonnes : on ne garde que
les seconds (audit du 31/10/2026, `alembic check`).

Revision ID: d7a1e5c3b820
Revises: c4e8a2d6f913
Create Date: 2026-10-31
"""

from alembic import op

revision = "d7a1e5c3b820"
down_revision = "c4e8a2d6f913"
branch_labels = None
depends_on = None

_PAIRS = (
    ("ix_player_equipment_set_items_equipment_set_id", "ix_player_equipment_set_items_set_id", "equipment_set_id"),
    ("ix_player_equipment_set_items_item_definition_id", "ix_player_equipment_set_items_item_id", "item_definition_id"),
)


def upgrade() -> None:
    for old, new, column in _PAIRS:
        op.execute(f"DROP INDEX IF EXISTS {old}")
        op.execute(f"CREATE INDEX IF NOT EXISTS {new} ON player_equipment_set_items ({column})")


def downgrade() -> None:
    pass        # noms seulement : rien à défaire
