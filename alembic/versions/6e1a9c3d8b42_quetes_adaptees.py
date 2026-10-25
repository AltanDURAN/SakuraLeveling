"""quêtes adaptées à chaque joueur

Revision ID: 6e1a9c3d8b42
Revises: 2d9c4b7e5f30
Create Date: 2026-10-25 19:00:00

Demande de l'auteur (25/10/2026) : les quêtes deviennent des MODÈLES, et
chaque joueur reçoit une quête CONCRÈTE (cible de sa zone, quantité à son
niveau, objectif de son rôle), figée sur l'assignation. Les assignations
d'avant (objectifs fixes, anciens codes) sont vidées : chacun reçoit ses
nouvelles quêtes à sa prochaine action.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "6e1a9c3d8b42"
down_revision: Union[str, Sequence[str], None] = "2d9c4b7e5f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("daily_quest_assignments", "weekly_quest_assignments")
COLUMNS = (
    ("name", sa.String(length=120), ""),
    ("description", sa.String(length=300), ""),
    ("tier", sa.String(length=10), "easy"),
    ("objective_type", sa.String(length=40), ""),
    ("objective_target", sa.String(length=100), ""),
    ("objective_quantity", sa.Integer(), "1"),
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"DELETE FROM {table}")
        with op.batch_alter_table(table) as batch:
            for name, kind, default in COLUMNS:
                batch.add_column(sa.Column(name, kind, nullable=False, server_default=default))


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DELETE FROM {table}")
        with op.batch_alter_table(table) as batch:
            for name, _kind, _default in COLUMNS:
                batch.drop_column(name)
