"""saison 1 : équipement v2 (drop par monstre, rareté, fusion, passifs)

Revision ID: 9b3e5f7a2c41
Revises: 8d2f4a6c1e33
Create Date: 2026-10-23 10:00:00

  • `player_gear` : une ligne par pièce POSSÉDÉE (rareté, forge sacrée,
    emplacement si portée) — les pièces ne sont plus fongibles ;
  • `item_definitions.passive` et `mob_definitions.gear_item_code` ;
  • suppression de TOUT l'ancien équipement (décision de l'auteur : on repart
    sur des règles fixes, et la saison 1 remet tout à zéro de toute façon) :
    pièces en inventaire, portées, niveaux d'amélioration, recettes, annonces
    de brocante, objets d'échange, commandes d'artisans, loadouts, puis les
    définitions elles-mêmes (le seed recrée les 23 nouvelles pièces).

`player_equipment` et `player_item_levels` restent en place, vides, le temps
que plus aucun code ne les lise ; une migration ultérieure les supprimera.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b3e5f7a2c41"
down_revision: Union[str, Sequence[str], None] = "8d2f4a6c1e33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GEAR_CATEGORIES = ("arme", "bouclier", "tete", "corps", "accessoire")


def upgrade() -> None:
    op.add_column("item_definitions", sa.Column(
        "passive", sa.String(64), server_default="", nullable=False))
    op.add_column("mob_definitions", sa.Column(
        "gear_item_code", sa.String(100), server_default="", nullable=False))

    op.create_table(
        "player_gear",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(),
                  sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_definition_id", sa.Integer(),
                  sa.ForeignKey("item_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rarity", sa.String(16), nullable=False, server_default="common"),
        sa.Column("forge_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("equipped_slot", sa.String(50), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="drop"),
        sa.Column("listed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_player_gear_player_id", "player_gear", ["player_id"])
    op.create_index("ix_player_gear_item_definition_id", "player_gear", ["item_definition_id"])
    op.create_index(
        "uq_player_gear_equipped_slot", "player_gear", ["player_id", "equipped_slot"],
        unique=True, sqlite_where=sa.text("equipped_slot IS NOT NULL"),
    )

    # Une pièce échangée ou vendue l'est en tant qu'EXEMPLAIRE précis.
    with op.batch_alter_table("trade_items") as batch:
        batch.add_column(sa.Column("gear_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("marketplace_listings") as batch:
        batch.add_column(sa.Column("gear_id", sa.Integer(), nullable=True))

    # ---- Suppression de l'ancien équipement ----
    cats = ", ".join(f"'{c}'" for c in _GEAR_CATEGORIES)
    old = f"(SELECT id FROM item_definitions WHERE category IN ({cats}))"
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM player_equipment"))
    conn.execute(sa.text("DELETE FROM player_item_levels"))
    conn.execute(sa.text(f"DELETE FROM player_inventory_items WHERE item_definition_id IN {old}"))
    conn.execute(sa.text(f"DELETE FROM player_equipment_set_items WHERE item_definition_id IN {old}"))
    conn.execute(sa.text(f"DELETE FROM marketplace_listings WHERE item_definition_id IN {old}"))
    conn.execute(sa.text(f"DELETE FROM trade_items WHERE item_definition_id IN {old}"))
    conn.execute(sa.text(f"DELETE FROM player_work_orders WHERE result_item_definition_id IN {old}"))
    conn.execute(sa.text(
        "DELETE FROM craft_recipe_ingredients WHERE craft_recipe_id IN "
        f"(SELECT id FROM craft_recipes WHERE result_item_definition_id IN {old})"
    ))
    conn.execute(sa.text(f"DELETE FROM craft_recipes WHERE result_item_definition_id IN {old}"))
    conn.execute(sa.text(f"DELETE FROM item_definitions WHERE id IN {old}"))


def downgrade() -> None:
    with op.batch_alter_table("marketplace_listings") as batch:
        batch.drop_column("gear_id")
    with op.batch_alter_table("trade_items") as batch:
        batch.drop_column("gear_id")
    op.drop_index("uq_player_gear_equipped_slot", table_name="player_gear")
    op.drop_index("ix_player_gear_item_definition_id", table_name="player_gear")
    op.drop_index("ix_player_gear_player_id", table_name="player_gear")
    op.drop_table("player_gear")
    with op.batch_alter_table("mob_definitions") as batch:
        batch.drop_column("gear_item_code")
    with op.batch_alter_table("item_definitions") as batch:
        batch.drop_column("passive")
