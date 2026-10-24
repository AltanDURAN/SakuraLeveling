"""ménage : tables de la fabrication et des abonnés à l'aide

Revision ID: 7d2b9e4f1a63
Revises: 4e7a1c9d2b58
Create Date: 2026-10-24 18:00:00

Audit d'octobre 2026. Ces tables ne sont plus lues ni écrites :
  • `craft_recipes` / `craft_recipe_ingredients` : la fabrication a été
    remplacée par la FUSION (équipement v2) ;
  • `player_work_orders` : les commandes d'artisans (fabrication avec délai) ;
    la maîtrise des artisans reste, dans `player_artisan_mastery` ;
  • `help_subscribers` : remplacé par le rôle @chad.
Le downgrade les recrée à l'identique (schéma SQLite d'origine), vides.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "7d2b9e4f1a63"
down_revision: Union[str, Sequence[str], None] = "4e7a1c9d2b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS craft_recipe_ingredients")
    op.execute("DROP TABLE IF EXISTS craft_recipes")
    op.execute("DROP TABLE IF EXISTS player_work_orders")
    op.execute("DROP TABLE IF EXISTS help_subscribers")


def downgrade() -> None:
    op.execute("""CREATE TABLE craft_recipes (
        id INTEGER NOT NULL, code VARCHAR(100) NOT NULL, name VARCHAR(100) NOT NULL,
        result_item_definition_id INTEGER NOT NULL, result_quantity INTEGER NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(result_item_definition_id) REFERENCES item_definitions (id))""")
    op.execute("CREATE UNIQUE INDEX ix_craft_recipes_code ON craft_recipes (code)")
    op.execute("CREATE INDEX ix_craft_recipes_result_item_definition_id ON craft_recipes (result_item_definition_id)")
    op.execute("""CREATE TABLE craft_recipe_ingredients (
        id INTEGER NOT NULL, craft_recipe_id INTEGER NOT NULL,
        item_definition_id INTEGER NOT NULL, quantity INTEGER NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(craft_recipe_id) REFERENCES craft_recipes (id),
        FOREIGN KEY(item_definition_id) REFERENCES item_definitions (id),
        CONSTRAINT uq_craft_ingredient UNIQUE (craft_recipe_id, item_definition_id))""")
    op.execute("CREATE INDEX ix_craft_recipe_ingredients_craft_recipe_id ON craft_recipe_ingredients (craft_recipe_id)")
    op.execute("CREATE INDEX ix_craft_recipe_ingredients_item_definition_id ON craft_recipe_ingredients (item_definition_id)")
    op.execute("""CREATE TABLE player_work_orders (
        id INTEGER NOT NULL, player_id INTEGER NOT NULL, artisan_code VARCHAR(40) NOT NULL,
        recipe_code VARCHAR(100) NOT NULL, result_item_definition_id INTEGER NOT NULL,
        result_quantity INTEGER NOT NULL, status VARCHAR(20) NOT NULL,
        gold_paid INTEGER NOT NULL, item_power INTEGER NOT NULL,
        started_at DATETIME NOT NULL, ready_at DATETIME NOT NULL, collected_at DATETIME,
        notify_channel_id INTEGER NOT NULL, notified INTEGER NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(player_id) REFERENCES players (id) ON DELETE CASCADE,
        FOREIGN KEY(result_item_definition_id) REFERENCES item_definitions (id) ON DELETE CASCADE)""")
    op.execute("CREATE INDEX ix_player_work_orders_artisan_code ON player_work_orders (artisan_code)")
    op.execute("CREATE INDEX ix_player_work_orders_player_id ON player_work_orders (player_id)")
    op.execute("CREATE INDEX ix_player_work_orders_status ON player_work_orders (status)")
    op.execute("CREATE INDEX ix_work_order_ready_at ON player_work_orders (status, ready_at)")
    op.execute("CREATE UNIQUE INDEX uq_player_active_work_order ON player_work_orders (player_id, artisan_code) "
               "WHERE status IN ('in_progress', 'ready')")
    op.execute("""CREATE TABLE help_subscribers (
        id INTEGER NOT NULL, player_id INTEGER NOT NULL, subscribed_at DATETIME NOT NULL,
        PRIMARY KEY (id), UNIQUE (player_id),
        FOREIGN KEY(player_id) REFERENCES players (id) ON DELETE CASCADE)""")
