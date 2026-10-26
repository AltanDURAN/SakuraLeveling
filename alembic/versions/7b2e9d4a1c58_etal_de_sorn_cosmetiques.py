"""Étal de Sorn : prix selon le niveau, un exemplaire max ; cosmétiques portés

Revision ID: 7b2e9d4a1c58
Revises: 3a7d5c1f9e64
Create Date: 2026-10-26 14:00:00

Décision de l'auteur (26/10/2026) : Sorn vend des outils (cor de chasse,
sceau du second souffle, parchemin d'oubli, jeton d'arbre, sablier de
fidélité) et des cosmétiques de profil.
  • `shop_items.price_per_level` : > 0 ⇒ prix = valeur × niveau du joueur
    (parchemin, jeton : ils rapportent plus à haut niveau) ; sinon prix fixe,
    le même pour tous ;
  • `shop_items.max_owned` : > 0 ⇒ achat refusé si on en a déjà autant ;
  • `player_cosmetics` : le fond, le cadre et la couleur de titre portés.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "7b2e9d4a1c58"
down_revision: Union[str, Sequence[str], None] = "3a7d5c1f9e64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("shop_items") as batch:
        batch.add_column(sa.Column("price_per_level", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("max_owned", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "player_cosmetics",
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("fond", sa.String(60), nullable=True),
        sa.Column("cadre", sa.String(60), nullable=True),
        sa.Column("titre", sa.String(60), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("player_cosmetics")
    with op.batch_alter_table("shop_items") as batch:
        batch.drop_column("max_owned")
        batch.drop_column("price_per_level")
