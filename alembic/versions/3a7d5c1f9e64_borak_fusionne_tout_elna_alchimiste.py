"""Borak fusionne tout, Elna devient alchimiste

Revision ID: 3a7d5c1f9e64
Revises: 6e1a9c3d8b42
Create Date: 2026-10-26 10:00:00

Demande de l'auteur (26/10/2026) : la fusion des accessoires passe chez Borak
(doublon avec Elna sinon) ; Elna prépare désormais les potions, et Sorn n'en
vend plus.
  • maîtrise : les fusions d'accessoires faites chez Elna (`artisan`) sont
    reportées sur Borak (`forgeron`) — personne ne perd sa remise ; la
    maîtrise d'alchimiste (`alchimiste`) part de zéro ;
  • boutique : la potion de soin quitte les rayons de Sorn.

Pas de changement de schéma (les élixirs utilisent `player_status_effects`).
Downgrade : rien (la maîtrise fusionnée ne se redécoupe pas).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "3a7d5c1f9e64"
down_revision: Union[str, Sequence[str], None] = "6e1a9c3d8b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT player_id, orders_completed, gold_spent FROM player_artisan_mastery "
        "WHERE artisan_code = 'artisan'"
    )).all()
    for player_id, orders, gold in rows:
        forge = bind.execute(sa.text(
            "SELECT id FROM player_artisan_mastery WHERE player_id = :p AND artisan_code = 'forgeron'"
        ), {"p": player_id}).first()
        if forge is None:
            bind.execute(sa.text(
                "INSERT INTO player_artisan_mastery (player_id, artisan_code, orders_completed, gold_spent, updated_at) "
                "VALUES (:p, 'forgeron', :o, :g, CURRENT_TIMESTAMP)"
            ), {"p": player_id, "o": orders or 0, "g": gold or 0})
        else:
            bind.execute(sa.text(
                "UPDATE player_artisan_mastery SET orders_completed = orders_completed + :o, "
                "gold_spent = gold_spent + :g WHERE id = :id"
            ), {"o": orders or 0, "g": gold or 0, "id": forge[0]})
    bind.execute(sa.text("DELETE FROM player_artisan_mastery WHERE artisan_code = 'artisan'"))

    bind.execute(sa.text(
        "DELETE FROM shop_items WHERE item_definition_id IN "
        "(SELECT id FROM item_definitions WHERE code = 'potion_soin')"
    ))


def downgrade() -> None:
    pass
