"""Record d'album : seules les cartes obtenues soi-même comptent

Revision ID: c1f7a3e9b246
Revises: a9d4c7e2f518
Create Date: 2026-11-14 14:00:00

`player_card_states.own_cards` : les codes des cartes ouvertes en booster ou
fabriquées par le joueur. Le record d'album ne compte plus les cartes reçues
par échange ou achetées (un groupe pouvait se les prêter avant la mise à jour
de minuit). Reprise : chacun garde comme siennes les cartes qu'il possède
aujourd'hui.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c1f7a3e9b246"
down_revision: Union[str, Sequence[str], None] = "a9d4c7e2f518"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("player_card_states", sa.Column("own_cards", sa.Text(), nullable=False, server_default=""))
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT i.player_id, d.code FROM player_inventory_items i "
        "JOIN item_definitions d ON d.id = i.item_definition_id "
        "WHERE d.category = 'carte' AND i.quantity > 0")).all()
    owned: dict[int, set[str]] = {}
    for player_id, code in rows:
        card = code.removeprefix("carte_").removesuffix("_brillante")
        owned.setdefault(player_id, set()).add(card)
    for player_id, codes in owned.items():
        bind.execute(sa.text("UPDATE player_card_states SET own_cards = :c, album_count = :n WHERE player_id = :p"),
                     {"c": ",".join(sorted(codes)), "n": len(codes), "p": player_id})


def downgrade() -> None:
    op.drop_column("player_card_states", "own_cards")
