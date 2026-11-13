"""Journal de surveillance : les fuites deviennent un compteur par heure

Revision ID: a9d4c7e2f518
Revises: f5c2e8a1b7d4
Create Date: 2026-11-13 03:30:00

Un monstre reparti sans combattant écrivait UNE ligne `flee` dans
`game_events` : 19 585 lignes sur 19 990 en onze jours (98 % du journal), alors
que la Surveillance n'en lit que le nombre par heure et par zone. Le bot tient
désormais un compteur — une ligne (zone, heure) dont `qty` monte
(`telemetry.count`). Cette migration regroupe les lignes existantes de la même
façon : rien n'est perdu de ce que les pages affichent.
"""
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a9d4c7e2f518"
down_revision: Union[str, Sequence[str], None] = "f5c2e8a1b7d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("game_events"):
        return
    events = sa.table(
        "game_events",
        sa.column("id", sa.Integer), sa.column("at", sa.DateTime), sa.column("kind", sa.String),
        sa.column("zone", sa.String), sa.column("qty", sa.Integer),
        sa.column("gold", sa.BigInteger), sa.column("xp", sa.BigInteger),
    )
    rows = bind.execute(sa.select(events.c.id, events.c.at, events.c.zone).where(events.c.kind == "flee")).all()
    if not rows:
        return
    hours: dict[tuple, int] = {}
    for _id, at, zone in rows:
        if isinstance(at, str):                      # SQLite rend parfois le texte brut
            at = datetime.fromisoformat(at)
        key = (zone, at.replace(minute=0, second=0, microsecond=0))
        hours[key] = hours.get(key, 0) + 1
    last_id = max(r[0] for r in rows)
    bind.execute(sa.delete(events).where(events.c.kind == "flee", events.c.id <= last_id))
    bind.execute(sa.insert(events), [
        {"at": hour, "kind": "flee", "zone": zone, "qty": n, "gold": 0, "xp": 0}
        for (zone, hour), n in sorted(hours.items(), key=lambda kv: (kv[0][1], kv[0][0] or ""))
    ])


def downgrade() -> None:
    # Le détail (une ligne par fuite, avec le monstre) n'est pas reconstituable ;
    # le compteur reste lisible par l'ancien code (il comptait les lignes).
    pass
