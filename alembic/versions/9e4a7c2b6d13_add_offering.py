"""Offrande commune : jauge du serveur et dons

Revision ID: 9e4a7c2b6d13
Revises: 5d2c8e1f4a90
Create Date: 2026-10-27 10:30:00

Idée de l'auteur (27/10/2026) : une jauge commune remplie en or invoque une
divinité au hasard qui bénit tout le serveur pour la journée ; une fois par
jour, de plus en plus chère à chaque remplissage.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "9e4a7c2b6d13"
down_revision: Union[str, Sequence[str], None] = "5d2c8e1f4a90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "offering_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("target", sa.Integer(), nullable=False, server_default="25000"),
        sa.Column("contributed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fills", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filled_on", sa.Date(), nullable=True),
        sa.Column("priced_on", sa.Date(), nullable=True),
        sa.Column("deity_code", sa.String(40), nullable=True),
        sa.Column("blessed_at", sa.DateTime(), nullable=True),
        sa.Column("blessing_until", sa.DateTime(), nullable=True),
        sa.Column("filled_by", sa.Integer(), nullable=True),
    )
    op.create_table(
        "offering_contributions",
        sa.Column("cycle", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("offering_contributions")
    op.drop_table("offering_state")
