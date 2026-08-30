"""Commandes passées aux artisans + maîtrise relationnelle par joueur."""

from datetime import datetime, UTC

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base

STATUS_IN_PROGRESS = "in_progress"
STATUS_READY = "ready"
STATUS_COLLECTED = "collected"
STATUS_CANCELLED = "cancelled"


class PlayerWorkOrderModel(Base):
    """Un travail commandé à un artisan (forge ou confection).

    Le joueur paie les ingrédients ET l'or AU MOMENT de la commande : le
    travail est engagé, l'artisan a déjà entamé la matière. L'annulation ne
    rembourse qu'une partie de l'or et rend les ingrédients.

    Un seul travail EN COURS par (joueur, artisan) — garanti par un index
    unique partiel, pas seulement par une vérification applicative : deux
    clics simultanés sur « Forger » ne doivent pas créer deux commandes.
    """

    __tablename__ = "player_work_orders"
    # Les index sont déclarés APRÈS la classe : l'unicité doit être PARTIELLE
    # (colonnes + condition), ce que `__table_args__` n'exprime pas ici.

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    artisan_code: Mapped[str] = mapped_column(String(40), index=True)
    recipe_code: Mapped[str] = mapped_column(String(100))
    result_item_definition_id: Mapped[int] = mapped_column(
        ForeignKey("item_definitions.id", ondelete="CASCADE")
    )
    result_quantity: Mapped[int] = mapped_column(Integer, default=1)

    status: Mapped[str] = mapped_column(
        String(20), default=STATUS_IN_PROGRESS, index=True
    )
    gold_paid: Mapped[int] = mapped_column(Integer, default=0)
    item_power: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
    ready_at: Mapped[datetime] = mapped_column(DateTime)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Salon où prévenir le joueur quand c'est prêt (0 = pas de notification).
    notify_channel_id: Mapped[int] = mapped_column(Integer, default=0)
    notified: Mapped[int] = mapped_column(Integer, default=0)


# L'unicité ne porte QUE sur les commandes actives : un joueur peut accumuler
# des dizaines de commandes terminées chez le même artisan. Index PARTIEL, donc
# la contrainte est tenue par la base — deux clics simultanés sur « Forger » ne
# peuvent pas créer deux commandes.
Index(
    "uq_player_active_work_order",
    PlayerWorkOrderModel.player_id,
    PlayerWorkOrderModel.artisan_code,
    unique=True,
    sqlite_where=PlayerWorkOrderModel.status.in_(
        [STATUS_IN_PROGRESS, STATUS_READY]
    ),
)
Index(
    "ix_work_order_ready_at",
    PlayerWorkOrderModel.status,
    PlayerWorkOrderModel.ready_at,
)


class PlayerArtisanMasteryModel(Base):
    """Maîtrise d'un artisan VIS-À-VIS d'un joueur.

    Elle ne mesure pas le talent du PNJ dans l'absolu mais la relation de
    travail : ce qu'il a déjà fabriqué pour ce joueur précis. Deux joueurs
    voient donc le même personnage à des paliers différents.
    """

    __tablename__ = "player_artisan_mastery"
    __table_args__ = (
        UniqueConstraint("player_id", "artisan_code", name="uq_player_artisan"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    artisan_code: Mapped[str] = mapped_column(String(40), index=True)
    orders_completed: Mapped[int] = mapped_column(Integer, default=0)
    gold_spent: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
