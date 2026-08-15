from datetime import datetime, UTC

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class ActiveEventModel(Base):
    """Instance d'un événement non-combat (coffre, petite fille, forge sacrée).

    Comme les world bosses : les DÉFINITIONS/params vivent dans `events.json`,
    les INSTANCES vivent en DB (pour résoudre à échéance et survivre au reboot).
    `payload_json` porte l'état spécifique (ex : loot roulé, issue piège/vraie).
    """

    __tablename__ = "active_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # active → resolved | expired
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")

    # Coffre : premier qui clique. NULL tant que personne n'a ouvert.
    winner_player_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
    # NULL = pas de résolution différée (coffre). Sinon échéance (5 min).
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )


class EventParticipationModel(Base):
    """Participation d'un joueur à un événement collectif (petite fille, forge).

    UNIQUE (event_id, player_id) : un joueur = une ligne, upsert (dernier choix
    gagne pour la petite fille). `choice` = "aider"/"ignorer" (petite fille) ou
    l'item forgé (forge). `payload_json` = détail (ex : item_definition_id forgé).
    """

    __tablename__ = "event_participations"
    __table_args__ = (
        UniqueConstraint("event_id", "player_id", name="uq_event_participation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("active_events.id", ondelete="CASCADE"), index=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    choice: Mapped[str] = mapped_column(String(40), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )


class EventSchedulerStateModel(Base):
    """État de l'orchestrateur de spawn : dernier spawn par type + ligne globale
    `__global__` pour l'espacement minimum d'1h entre deux spawns (tous types)."""

    __tablename__ = "event_scheduler_state"

    event_type: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_spawn_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
