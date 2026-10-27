"""Assemble les données réelles du raid pour la bannière (rendu pur ailleurs).

Séparé du cog pour être testable sans Discord : on lit la DB et on produit un
`RaidBannerData`. Le rendu PNG, lui, ne connaît que ce dataclass.
"""

from __future__ import annotations

from datetime import datetime, UTC
from zoneinfo import ZoneInfo

from app.bot.rendering.world_boss_banner import Contributor, RaidBannerData
from app.domain.entities.world_boss import WorldBoss
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.world_boss_repository import (
    WorldBossRepository,
)
from app.domain.services import element_service, pacing_service
from app.infrastructure.pacing.pacing_loader import get_pacing
from app.shared.enums import ELEMENT_EMOJIS, ELEMENT_LABELS

_PARIS = ZoneInfo("Europe/Paris")
RAID_DAYS = 7


def next_assault_label(now: datetime | None = None, raid=None) -> str:
    """« 21h00 aujourd'hui (dans 4 h 12) » — le rendez-vous quotidien du raid
    (heure réglable depuis l'admin, Monde › Rythme)."""
    raid = raid or get_pacing().raid
    now = (now or datetime.now(UTC)).astimezone(_PARIS)
    target = pacing_service.next_fight_at(raid, now)
    delta = target - now
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    minutes = rem // 60
    when = "aujourd'hui" if target.date() == now.date() else "demain"
    label = f"{target.hour}h{target.minute:02d}"
    if hours >= 1:
        return f"{label} {when} (dans {hours} h {minutes:02d})"
    return f"{label} {when} (dans {minutes} min)"


def raid_day_index(spawned_at: datetime, now: datetime | None = None) -> int:
    """Jour N du raid (1 = jour du spawn), borné à RAID_DAYS."""
    now = now or datetime.now(UTC)
    if spawned_at.tzinfo is None:
        spawned_at = spawned_at.replace(tzinfo=UTC)
    days = (now - spawned_at).days + 1
    return max(1, min(RAID_DAYS, days))


def week_label(spawned_at: datetime) -> str:
    return f"Semaine {spawned_at.isocalendar().week}"


def build_raid_banner_data(session, boss: WorldBoss) -> RaidBannerData:
    """Lit les participations et construit les données d'affichage du raid."""
    repo = WorldBossRepository(session)
    player_repo = PlayerRepository(session)

    metrics = repo.list_participations_with_metrics(boss.id)
    contributors: list[Contributor] = []
    for part in metrics:
        profile = player_repo.get_profile_by_player_id(part.player_id)
        name = profile.player.display_name if profile else f"#{part.player_id}"
        contributors.append(
            Contributor(
                display_name=name,
                damage=part.damage_dealt,
                tanked=part.damage_tanked,
                healed=part.hp_healed,
            )
        )
    contributors.sort(key=lambda c: c.damage, reverse=True)

    return RaidBannerData(
        boss_name=boss.name,
        image_name=boss.image_name or "",
        current_hp=max(0, boss.current_hp),
        max_hp=boss.max_hp,
        element_label=ELEMENT_LABELS.get(boss.element, "") if boss.element else "",
        element_emoji=ELEMENT_EMOJIS.get(boss.element, "") if boss.element else "",
        week_label=week_label(boss.spawned_at),
        day_index=raid_day_index(boss.spawned_at),
        day_total=RAID_DAYS,
        warriors=len(metrics),
        assaults=sum(p.fights_count for p in metrics),
        next_assault=next_assault_label(),
        contributors=contributors,
        defeated=not boss.is_alive,
        attack=boss.attack,
        defense=boss.defense,
        speed=boss.speed,
        crit_chance=int(boss.crit_chance),
        weaknesses=_weakness_label(boss.element),
        element_code=boss.element or "",
        registered=repo.count_joined(boss.id),
    )


def _weakness_label(element: str) -> str:
    """Éléments qui battent le boss — information tactique qui pousse à
    composer une équipe plutôt qu'à foncer seul."""
    if not element:
        return ""
    weak = element_service.weaknesses_of(element)
    return " · ".join(
        f"{ELEMENT_EMOJIS.get(e.value, '')} {ELEMENT_LABELS.get(e.value, e.value)}"
        for e in weak
    )
