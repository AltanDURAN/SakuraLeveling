"""Records du serveur (salon des records)

Revision ID: b7e3c9a5d2f1
Revises: a6d2f8c4e1b7
Create Date: 2026-11-07 20:00:00

Meilleurs exploits de chaque joueur en combat de zone, détenteurs publiés la
nuit dernière, et état du tableau (nuit traitée, message).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b7e3c9a5d2f1"
down_revision: Union[str, Sequence[str], None] = "a6d2f8c4e1b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.String(120), nullable=False, server_default=""),
        sa.Column("achieved_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("player_id", "code", name="uq_player_record"),
    )
    op.create_index("ix_player_records_player_id", "player_records", ["player_id"])
    op.create_table(
        "record_holders",
        sa.Column("code", sa.String(40), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("detail", sa.String(120), nullable=False, server_default=""),
        sa.Column("achieved_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_record_holders_player_id", "record_holders", ["player_id"])
    op.create_table(
        "record_board",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_day", sa.Date(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("record_board")
    op.drop_index("ix_record_holders_player_id", table_name="record_holders")
    op.drop_table("record_holders")
    op.drop_index("ix_player_records_player_id", table_name="player_records")
    op.drop_table("player_records")
