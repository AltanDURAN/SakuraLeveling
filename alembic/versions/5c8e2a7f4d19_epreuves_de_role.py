"""épreuves de rôle quotidiennes, fin des duels JcJ

Revision ID: 5c8e2a7f4d19
Revises: 7d2b9e4f1a63
Create Date: 2026-10-25 12:00:00

Étape 2 de la refonte des rôles (décision de l'auteur, 25/10/2026) : les
duels JcJ sont REMPLACÉS par des épreuves de rôle quotidiennes (`/defi`).
  • `role_trial_scores` : meilleur score du jour par (joueur, jour, rôle) ;
  • `role_trial_weeks` : semaines clôturées (titres et or déjà distribués) ;
  • `player_duel_ranks` supprimée, ainsi que le titre `champion_1v1` (remplacé
    par « Champion de la semaine ») et le temps de recharge `duel_challenge`.
Le downgrade recrée la table des duels (vide) et supprime les deux nouvelles.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "5c8e2a7f4d19"
down_revision: Union[str, Sequence[str], None] = "7d2b9e4f1a63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "role_trial_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("variant_code", sa.String(length=30), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", "day", "role", name="uq_role_trial_day"),
    )
    op.create_index("ix_role_trial_scores_player_id", "role_trial_scores", ["player_id"])
    op.create_index("ix_role_trial_scores_day", "role_trial_scores", ["day"])
    op.create_table(
        "role_trial_weeks",
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=False),
        sa.Column("results_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("week_start"),
    )
    op.execute("DROP TABLE IF EXISTS player_duel_ranks")
    op.execute("DELETE FROM player_titles WHERE title_code = 'champion_1v1'")
    op.execute("DELETE FROM player_cooldowns WHERE action_key = 'duel_challenge'")


def downgrade() -> None:
    op.drop_table("role_trial_weeks")
    op.drop_index("ix_role_trial_scores_day", table_name="role_trial_scores")
    op.drop_index("ix_role_trial_scores_player_id", table_name="role_trial_scores")
    op.drop_table("role_trial_scores")
    op.execute("""CREATE TABLE player_duel_ranks (
        id INTEGER NOT NULL, player_id INTEGER NOT NULL, rank_position INTEGER NOT NULL,
        wins INTEGER DEFAULT '0' NOT NULL, losses INTEGER DEFAULT '0' NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        PRIMARY KEY (id), UNIQUE (player_id),
        FOREIGN KEY(player_id) REFERENCES players (id) ON DELETE CASCADE)""")
    op.execute("CREATE INDEX ix_player_duel_ranks_rank_position ON player_duel_ranks (rank_position)")
