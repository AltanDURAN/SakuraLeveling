"""Records du serveur (salon des records, 07/11/2026).

`player_records` : le meilleur EXPLOIT de chaque joueur en combat de zone (les
autres records se lisent dans les tables du jeu : défis, tour, raid, kills).
`record_holders` : les détenteurs publiés la nuit dernière (pour dire ce qui
a changé). `record_board` : la nuit déjà traitée et le message du tableau.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerRecordModel(Base):
    __tablename__ = "player_records"
    __table_args__ = (UniqueConstraint("player_id", "code", name="uq_player_record"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    value: Mapped[int] = mapped_column(Integer, default=0)
    #: Contre qui (les monstres du combat).
    detail: Mapped[str] = mapped_column(String(120), default="")
    achieved_at: Mapped[datetime] = mapped_column(DateTime)


class RecordHolderModel(Base):
    __tablename__ = "record_holders"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    value: Mapped[int] = mapped_column(Integer)
    detail: Mapped[str] = mapped_column(String(120), default="")
    #: Quand le détenteur a atteint cette valeur.
    achieved_at: Mapped[datetime] = mapped_column(DateTime)


class RecordBoardModel(Base):
    """Une seule ligne (id = 1)."""

    __tablename__ = "record_board"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Dernière nuit traitée (jour de Paris) : une seule mise à jour par jour.
    last_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
