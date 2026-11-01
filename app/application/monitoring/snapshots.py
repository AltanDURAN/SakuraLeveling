"""Photo quotidienne de chaque joueur (`player_daily_snapshots`).

Le bot la refait toutes les 30 min (une ligne par joueur et par JOUR de
Paris, écrasée jusqu'à minuit) : la dernière photo d'un jour est son état du
soir. Elle donne les courbes de progression (niveau, or, puissance), le build
(points, classes, pièces portées) et le contrôle de l'or : solde de la photo
+ mouvements du journal depuis = solde réel, sinon de l'or est apparu ou a
disparu sans passer par le jeu.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application.services.combat_passives_resolver import resolve_player_power
from app.application.services.player_stats_resolver import resolve_player_stats
from app.domain.services.monitoring.progression import total_xp
from app.domain.services.pacing_service import PARIS
from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.models.monitoring_model import GameEventModel, PlayerDailySnapshotModel
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.models.tower_progress_model import PlayerTowerProgressModel
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.skill_tree.skill_tree_loader import get_definition as get_skill_tree_definition

_logger = logging.getLogger(__name__)

SPECIALIZATION_GROUP = "spécialisation"


def local_day(now: datetime) -> date:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(PARIS).date()


def build_of(tree: SkillTreeService, allocations: dict[str, int]) -> tuple[list[str], str]:
    """(classes obtenues, spécialisation ou "")."""
    classes = tree.class_names(allocations)
    spec = ""
    for code, level in allocations.items():
        node = tree.definition.get(code)
        if node is not None and level > 0 and getattr(node, "exclusive_group", "") == SPECIALIZATION_GROUP:
            spec = node.name
    return classes, spec


def take_snapshots(session: Session, ranks: dict[int, str] | None = None,
                   now: datetime | None = None) -> int:
    """Photographie tous les joueurs (rang Discord dans `ranks`, par
    player_id, quand le bot le connaît). Renvoie le nombre de photos."""
    now = now or datetime.now(UTC)
    day = local_day(now)
    taken_at = now.astimezone(UTC).replace(tzinfo=None)
    ranks = ranks or {}
    definition = get_skill_tree_definition()
    tree = SkillTreeService(definition)
    kills = PlayerKillRepository(session)
    allocations_repo = PlayerSkillAllocationRepository(session)
    equipment = EquipmentRepository(session)
    # Contrôle de l'or : les soldes et le dernier événement du journal sont lus
    # dans la MÊME lecture, avant tout calcul (un calcul peut valider la
    # transaction). Tout mouvement d'or validé après a un numéro plus grand :
    # pas de course possible, contrairement à une comparaison d'heures.
    last_event = session.execute(select(func.max(GameEventModel.id))).scalar() or 0
    golds = dict(session.execute(select(PlayerResourceModel.player_id, PlayerResourceModel.gold)).all())
    count = 0
    for profile in PlayerRepository(session).list_all_profiles():
        pid = profile.player.id
        try:
            worn = equipment.list_by_player_id(pid)
            stats = resolve_player_stats(session, profile, worn)
            power = resolve_player_power(session, pid, stats)
            allocations = allocations_repo.list_by_player(pid)
            classes, spec = build_of(tree, allocations)
            prog = session.get(PlayerProgressionModel, pid)
            career = session.get(PlayerCareerStatsModel, pid)
            tower = session.get(PlayerTowerProgressModel, pid)
            data = {
                "eid": last_event,
                "pts": [prog.points_attack, prog.points_defense, prog.points_max_hp] if prog else [0, 0, 0],
                "free": [profile.progression.stat_points, profile.progression.skill_points],
                "classes": classes, "spec": spec,
                "tactic": getattr(profile.player, "combat_tactic", "") or "",
                "panoplie": getattr(profile.player, "panoplie_bonus", "") or "",
                "gear": [[w.item_definition.code, w.rarity] for w in worn],
                "tree": sum(allocations.values()),
                "tower": tower.best_floor if tower else 0,
                "stats": {"atk": stats.attack, "def": stats.defense, "hp": stats.max_hp,
                          "spd": stats.speed, "crit": stats.crit_chance, "dodge": stats.dodge},
            }
            row = session.get(PlayerDailySnapshotModel, (day, pid))
            if row is None:
                row = PlayerDailySnapshotModel(day=day, player_id=pid)
                session.add(row)
            row.taken_at = taken_at
            row.level = profile.progression.level
            row.xp_total = total_xp(profile.progression.level, profile.progression.xp)
            row.gold = golds.get(pid, profile.resources.gold)
            row.power = int(power)
            row.rank = ranks.get(pid, row.rank or "")
            row.kills = kills.get_total_kills(pid)
            row.combats = career.combats_fought if career else 0
            row.wins = career.combats_won if career else 0
            row.gold_earned = career.gold_earned_total if career else 0
            row.data = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            count += 1
        except Exception:  # noqa: BLE001 — un joueur cassé ne bloque pas les autres
            _logger.warning("photo de surveillance impossible pour le joueur %s", pid, exc_info=True)
    session.commit()
    return count
