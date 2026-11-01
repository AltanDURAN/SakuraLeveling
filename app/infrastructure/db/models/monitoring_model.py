"""Surveillance du jeu (01/11/2026, demande de l'auteur : des stats, des suivis
et des alertes dans le site admin pour équilibrer le jeu et repérer les
comportements suspects).

  • `game_events` — le JOURNAL : une ligne par chose qui arrive (interaction,
    combat, mouvement d'or, niveau, achat, fusion, promotion…). Pas de clé
    étrangère : on écrit vite, et un joueur reseté est purgé à la main
    (`ResetPlayerUseCase`).
  • `player_daily_snapshots` — une PHOTO de chaque joueur par jour (niveau,
    or, puissance, rang, build), mise à jour toutes les 30 min par le bot :
    les courbes de progression et le contrôle de l'or.
  • `monitoring_alerts` — l'historique des alertes (depuis quand, sourdine,
    notification envoyée aux admins).
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class GameEventModel(Base):
    __tablename__ = "game_events"
    __table_args__ = (
        Index("ix_game_events_at", "at"),
        Index("ix_game_events_kind_at", "kind", "at"),
        Index("ix_game_events_player_at", "player_id", "at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: Instant UTC (naïf, comme le reste de la base).
    at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    #: Type d'événement (cf. `monitoring.kinds`).
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    player_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Pour ce qui arrive avant le profil (arrivée sur le serveur, 1re commande).
    discord_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: Salon de zone d'un combat.
    zone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: L'objet de l'événement : monstre, objet, commande, source d'or…
    ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    gold: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    xp: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    qty: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: Détails en JSON (résultat d'un combat, rareté d'une pièce…).
    data: Mapped[str | None] = mapped_column(Text, nullable=True)


class PlayerDailySnapshotModel(Base):
    __tablename__ = "player_daily_snapshots"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    player_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1)
    #: XP cumulée depuis le niveau 1 (pour mesurer un rythme d'un niveau à l'autre).
    xp_total: Mapped[int] = mapped_column(BigInteger, default=0)
    gold: Mapped[int] = mapped_column(BigInteger, default=0)
    power: Mapped[int] = mapped_column(BigInteger, default=0)
    #: Rang porté (rôle Discord) ; "" si inconnu.
    rank: Mapped[str] = mapped_column(String(8), default="")
    kills: Mapped[int] = mapped_column(Integer, default=0)
    combats: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    gold_earned: Mapped[int] = mapped_column(BigInteger, default=0)
    #: Build (points de stats, classes, spécialisation, pièces portées…) en JSON.
    data: Mapped[str | None] = mapped_column(Text, nullable=True)


class MonitoringAlertModel(Base):
    __tablename__ = "monitoring_alerts"

    #: Identifiant stable : règle + objet (« gold_rate:42 », « mob_too_easy:slime »).
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(12), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    player_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    muted_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
