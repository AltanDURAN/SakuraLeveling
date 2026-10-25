"""suppression des ressources inutiles

Revision ID: 2d9c4b7e5f30
Revises: 8f3b6d1e9a27
Create Date: 2026-10-25 18:00:00

Audit du 24/10/2026, demande de l'auteur : 34 ressources ne servaient plus à
rien depuis la fin de la fabrication (seuls les 8 drops de FAMILLE servent, à
la fusion). Elles tombaient encore des monstres et encombraient l'inventaire ;
le diamant du coffre aussi. Retirées du contenu (items.json, butin des
monstres, coffre) ; ici, de la base : définitions et toutes leurs références
(inventaires, sets, échanges, brocante, boutique) — comme `DeleteItemUseCase`.

Downgrade : rien (le seed ne les recrée pas, elles n'existent plus au contenu).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "2d9c4b7e5f30"
down_revision: Union[str, Sequence[str], None] = "8f3b6d1e9a27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USELESS_CODES = (
    "bandelette_maudite", "bois", "braise_infernale", "chair_putride", "coeur_de_granit",
    "corne_d_archidemon", "corne_de_demon", "corne_naissante", "croc_d_ogre", "croc_triple",
    "cuir_brut", "dent_gatee", "diamant", "echo_de_cri", "eclat_de_pierre",
    "encre_rituelle", "essence_de_vie", "flamme_sacree", "gourde_de_chaman",
    "grappin_rouille", "lambeau_de_vetement", "larme_spectrale", "morceau_de_tissu",
    "noyau_de_slime", "os_massif", "os_poli", "petite_bombe", "philtre_de_charme",
    "pierre_runique", "plume_noircie", "poussiere_d_ossements", "resine_d_embaumement",
    "silex", "toile_de_dirigeable",
)

#: Tables qui référencent un objet par `item_definition_id` (cf. DeleteItemUseCase).
REF_TABLES = (
    "player_inventory_items", "player_gear", "player_equipment_set_items",
    "trade_items", "marketplace_listings", "shop_items",
)


def upgrade() -> None:
    bind = op.get_bind()
    codes = ", ".join(f"'{c}'" for c in USELESS_CODES)
    ids = [row[0] for row in bind.exec_driver_sql(
        f"SELECT id FROM item_definitions WHERE code IN ({codes})").fetchall()]
    if not ids:
        return
    id_list = ", ".join(str(i) for i in ids)
    existing = {row[0] for row in bind.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    for table in REF_TABLES:
        if table in existing:
            op.execute(f"DELETE FROM {table} WHERE item_definition_id IN ({id_list})")
    op.execute(f"DELETE FROM item_definitions WHERE id IN ({id_list})")


def downgrade() -> None:
    pass
