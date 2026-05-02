"""Use cases du système de world boss.

6 use cases regroupés pour cohérence :
    1. SpawnWorldBossUseCase — spawn manuel à partir d'une BossDefinition (JSON)
    2. SpawnRandomWorldBossUseCase — auto-spawn pondéré par spawn_weight
    3. JoinWorldBossUseCase — joueur s'inscrit à la session
    4. LeaveWorldBossUseCase — joueur se désinscrit (refus s'il a déjà combattu)
    5. FightWorldBossUseCase — solo combat avec bonus d'équipe + cooldown 1/jour
       + application des modifiers (immunity threshold, enrage, crit immunity)
    6. CompleteWorldBossUseCase — récompenses à la défaite

Convention HP/résultat : on réutilise `CombatService.fight_player_vs_mob` en
wrappant le boss dans une `MobDefinition` éphémère.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta

from app.domain.entities.boss_definition import BossDefinition
from app.domain.entities.mob_definition import MobDefinition
from app.domain.entities.world_boss import WorldBoss, WorldBossParticipation
from app.domain.services.boss_modifier_service import BossModifierService
from app.domain.services.combat_service import CombatService
from app.domain.services.cooldown_service import CooldownService
from app.domain.services.progression_service import ProgressionService
from app.domain.services.skill_tree_service import SkillTreeService
from app.domain.services.stats_service import StatsService
from app.domain.services.world_boss_scaling_service import WorldBossScalingService
from app.domain.value_objects.battle_result import BattleResult
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.world_boss_repository import WorldBossRepository
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)
from app.infrastructure.world_boss.boss_definition_loader import (
    get_definition as get_boss_definition,
    pick_random_definition,
)


BOSS_FIGHT_COOLDOWN_KEY = "world_boss_fight"
BOSS_RESPAWN_COOLDOWN_DAYS = 7  # 7 jours après défaite avant un nouveau spawn
DAILY_RESET_HOUR_UTC = 0  # reset à minuit UTC


def _next_midnight_utc(now: datetime) -> datetime:
    tomorrow = (now + timedelta(days=1)).replace(
        hour=DAILY_RESET_HOUR_UTC, minute=0, second=0, microsecond=0
    )
    return tomorrow


def _normalize_utc(dt: datetime) -> datetime:
    """SQLite renvoie des datetimes naïfs ; on assume UTC pour les comparaisons."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _boss_to_mob_definition(
    boss: WorldBoss,
    overridden_attack: int | None = None,
) -> MobDefinition:
    """Wrappe un WorldBoss en MobDefinition pour réutiliser CombatService.

    `overridden_attack` permet d'injecter une attack ajustée par les
    modifiers (ex : enrage). Si None, on utilise la valeur native du boss.
    """
    return MobDefinition(
        id=-1,  # sentinel : pas en DB en tant que mob
        code=boss.code,
        name=boss.name,
        description="",
        image_name=boss.image_name,
        family="world_boss",
        max_hp=boss.max_hp,
        current_hp=boss.current_hp,
        attack=overridden_attack if overridden_attack is not None else boss.attack,
        defense=boss.defense,
        speed=boss.speed,
        crit_chance=boss.crit_chance,
        crit_damage=boss.crit_damage,
        dodge=boss.dodge,
        hp_regeneration=0,  # un boss ne regagne jamais de PV
        xp_reward=0,
        gold_reward=0,
        spawn_weight=0,
        loot_table=None,
        created_at=boss.spawned_at,
        updated_at=boss.spawned_at,
    )


def _create_boss_from_definition(
    repo: WorldBossRepository, definition: BossDefinition
) -> WorldBoss:
    return repo.create(
        code=definition.code,
        name=definition.name,
        image_name=definition.image_name,
        max_hp=definition.max_hp,
        attack=definition.attack,
        defense=definition.defense,
        speed=definition.speed,
        crit_chance=definition.crit_chance,
        crit_damage=definition.crit_damage,
        dodge=definition.dodge,
        hp_regeneration=0,
    )


# ---------- 1. Spawn ----------


@dataclass
class SpawnBossResult:
    success: bool
    message: str
    boss: WorldBoss | None = None


class SpawnWorldBossUseCase:
    """Spawn manuel d'un world boss à partir de son code (BossDefinition JSON).

    Refuse s'il y a déjà un boss actif. La définition vient de
    `app/infrastructure/content/boss_definitions.json` — édition à chaud
    possible (clear le cache du loader).
    """

    def __init__(self, world_boss_repository: WorldBossRepository) -> None:
        self.world_boss_repository = world_boss_repository

    def execute(self, boss_code: str) -> SpawnBossResult:
        existing = self.world_boss_repository.get_active()
        if existing is not None:
            return SpawnBossResult(
                success=False,
                message=(
                    f"❌ Un world boss est déjà actif : **{existing.name}** "
                    f"({existing.current_hp:,}/{existing.max_hp:,} PV)."
                ),
            )

        definition = get_boss_definition(boss_code)
        if definition is None:
            return SpawnBossResult(
                success=False, message=f"❌ Boss `{boss_code}` introuvable."
            )

        boss = _create_boss_from_definition(self.world_boss_repository, definition)
        return SpawnBossResult(
            success=True,
            message=(f"⚡ **{boss.name}** apparaît avec **{boss.max_hp:,}** PV !"),
            boss=boss,
        )


@dataclass
class AutoSpawnDecision:
    spawned: bool
    reason: str
    boss: WorldBoss | None = None


class SpawnRandomWorldBossUseCase:
    """Auto-spawn aléatoire pondéré par `spawn_weight` des définitions.

    Conditions de spawn (toutes doivent être vraies) :
        1. Aucun boss actif actuellement
        2. Soit aucun boss n'a jamais été spawn, soit le dernier mort
           a été défait il y a ≥ BOSS_RESPAWN_COOLDOWN_DAYS jours
        3. Tirage aléatoire : par défaut `spawn_probability` = 0.05 (5%
           de chance par appel — ajustable). Avec un loop horaire, ça
           donne en moyenne ~1 spawn / jour après la fenêtre 7j → on
           reste cohérent avec "1 par semaine" en moyenne (le user peut
           ajuster).

    Le caller est responsable d'appeler ce use case périodiquement.
    """

    def __init__(
        self,
        world_boss_repository: WorldBossRepository,
        spawn_probability: float = 0.05,
    ) -> None:
        self.world_boss_repository = world_boss_repository
        self.spawn_probability = spawn_probability

    def execute(
        self,
        now: datetime | None = None,
        rng: random.Random | None = None,
        force: bool = False,
    ) -> AutoSpawnDecision:
        now = now or datetime.now(UTC)
        rng = rng or random

        if self.world_boss_repository.get_active() is not None:
            return AutoSpawnDecision(False, "boss_actif")

        last_defeated = self.world_boss_repository.get_latest_defeated()
        if last_defeated is not None:
            elapsed = now - _normalize_utc(last_defeated.defeated_at)
            if elapsed < timedelta(days=BOSS_RESPAWN_COOLDOWN_DAYS):
                return AutoSpawnDecision(
                    False, f"cooldown_respawn ({elapsed.days}j sur 7j)"
                )

        # Tirage aléatoire (sauf si force=True pour les tests)
        if not force and rng.random() > self.spawn_probability:
            return AutoSpawnDecision(False, "tirage_negatif")

        definition = pick_random_definition(rng=rng)
        if definition is None:
            return AutoSpawnDecision(False, "aucune_definition")

        boss = _create_boss_from_definition(self.world_boss_repository, definition)
        return AutoSpawnDecision(
            spawned=True, reason="ok", boss=boss,
        )


# ---------- 2. Join / Leave ----------


@dataclass
class JoinLeaveResult:
    success: bool
    message: str


class JoinWorldBossUseCase:
    def __init__(
        self,
        world_boss_repository: WorldBossRepository,
        player_repository: PlayerRepository,
    ) -> None:
        self.world_boss_repository = world_boss_repository
        self.player_repository = player_repository

    def execute(
        self, discord_id: int, username: str, display_name: str,
    ) -> JoinLeaveResult:
        boss = self.world_boss_repository.get_active()
        if boss is None or not boss.is_alive:
            return JoinLeaveResult(False, "❌ Aucun world boss actif.")

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name,
        )
        existing = self.world_boss_repository.get_participation(boss.id, profile.player.id)
        if existing is not None and existing.joined:
            return JoinLeaveResult(False, "⚠️ Vous êtes déjà inscrit à ce raid.")

        self.world_boss_repository.upsert_participation(
            boss.id, profile.player.id, joined=True
        )
        count = self.world_boss_repository.count_joined(boss.id)
        word = "joueur" if count <= 1 else "joueurs"
        return JoinLeaveResult(
            True,
            f"✅ Vous rejoignez le raid contre **{boss.name}** (raid à {count} {word}).",
        )


class LeaveWorldBossUseCase:
    def __init__(
        self,
        world_boss_repository: WorldBossRepository,
        player_repository: PlayerRepository,
    ) -> None:
        self.world_boss_repository = world_boss_repository
        self.player_repository = player_repository

    def execute(self, discord_id: int) -> JoinLeaveResult:
        boss = self.world_boss_repository.get_active()
        if boss is None or not boss.is_alive:
            return JoinLeaveResult(False, "❌ Aucun world boss actif.")

        profile = self.player_repository.get_by_discord_id(discord_id)
        if profile is None:
            return JoinLeaveResult(False, "❌ Vous n'avez pas de profil joueur.")

        existing = self.world_boss_repository.get_participation(boss.id, profile.player.id)
        if existing is None or not existing.joined:
            return JoinLeaveResult(False, "⚠️ Vous n'étiez pas inscrit.")
        if existing.fights_count > 0:
            return JoinLeaveResult(
                False,
                "⚠️ Vous avez déjà combattu ce boss : impossible de quitter le raid.",
            )

        self.world_boss_repository.upsert_participation(
            boss.id, profile.player.id, joined=False
        )
        return JoinLeaveResult(True, "🚪 Vous quittez le raid.")


# ---------- 3. Fight ----------


@dataclass
class FightBossResult:
    success: bool
    message: str
    battle_result: BattleResult | None = None
    boss_remaining_hp: int = 0
    boss_max_hp: int = 0
    team_bonus_pct: int = 0
    boss_defeated: bool = False


class FightWorldBossUseCase:
    """Lance le combat solo d'un joueur contre le boss.

    Règles :
        • Le joueur doit être inscrit (joined=True)
        • Cooldown 1 combat/jour reset à minuit UTC
        • Stats du joueur boostées par le `team_bonus_multiplier`
        • Le boss garde ses HP réels (current_hp persisté)
        • Le boss ne regen JAMAIS de PV (hp_regeneration=0 par construction)
        • La participation cumule damage_dealt / tanked / hp_healed
    """

    def __init__(
        self,
        world_boss_repository: WorldBossRepository,
        player_repository: PlayerRepository,
        equipment_repository: EquipmentRepository,
        class_repository: ClassRepository,
        skill_allocation_repository: PlayerSkillAllocationRepository,
        cooldown_repository: CooldownRepository,
        stats_service: StatsService,
        scaling_service: WorldBossScalingService,
        combat_service: CombatService,
        cooldown_service: CooldownService,
        modifier_service: BossModifierService | None = None,
    ) -> None:
        self.world_boss_repository = world_boss_repository
        self.player_repository = player_repository
        self.equipment_repository = equipment_repository
        self.class_repository = class_repository
        self.skill_allocation_repository = skill_allocation_repository
        self.cooldown_repository = cooldown_repository
        self.stats_service = stats_service
        self.scaling_service = scaling_service
        self.combat_service = combat_service
        self.cooldown_service = cooldown_service
        self.modifier_service = modifier_service or BossModifierService()

    def execute(
        self, discord_id: int, username: str, display_name: str,
    ) -> FightBossResult:
        boss = self.world_boss_repository.get_active()
        if boss is None or not boss.is_alive:
            return FightBossResult(False, "❌ Aucun world boss actif.")

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name,
        )
        participation = self.world_boss_repository.get_participation(
            boss.id, profile.player.id
        )
        if participation is None or not participation.joined:
            return FightBossResult(
                False, "❌ Vous devez d'abord rejoindre le raid."
            )

        # Cooldown 1/jour
        now = datetime.now(UTC)
        cooldown = self.cooldown_repository.get_by_player_and_action(
            profile.player.id, BOSS_FIGHT_COOLDOWN_KEY
        )
        if not self.cooldown_service.is_available(cooldown, now):
            ts = int(cooldown.next_available_at.timestamp())
            return FightBossResult(
                False,
                f"⏳ Vous avez déjà combattu aujourd'hui. Reset <t:{ts}:R>.",
            )

        # Calcul des stats avec bonus d'équipe
        equipped = self.equipment_repository.list_by_player_id(profile.player.id)
        active_class = self.class_repository.get_current_class_for_player(profile.player.id)
        allocations = self.skill_allocation_repository.list_by_player(profile.player.id)
        skill_bonuses = SkillTreeService(get_skill_tree_definition()).aggregate_bonuses(
            allocations
        )
        base_stats = self.stats_service.calculate_player_stats(
            profile=profile,
            equipped_items=equipped,
            active_class=active_class,
            skill_bonuses=skill_bonuses,
        )
        num_participants = self.world_boss_repository.count_joined(boss.id)
        boosted_stats = self.scaling_service.apply_team_bonus(base_stats, num_participants)
        team_bonus_pct = int(
            (self.scaling_service.compute_team_bonus_multiplier(num_participants) - 1) * 100
        )

        # Récupérer les modifiers depuis la BossDefinition (si présente)
        boss_def = get_boss_definition(boss.code)
        modifiers = boss_def.modifiers if boss_def is not None else {}

        # Application des modifiers : enrage (mult atk boss) + crit_immunity
        adjustments = self.modifier_service.compute_adjustments(
            modifiers=modifiers,
            boss_max_hp=boss.max_hp,
            boss_current_hp=boss.current_hp,
            boss_attack=boss.attack,
            player_crit_chance=boosted_stats.crit_chance,
        )

        # Si crit immunity actif, on neutralise la crit_chance du joueur
        if adjustments.player_crit_chance != boosted_stats.crit_chance:
            boosted_stats = type(boosted_stats)(
                max_hp=boosted_stats.max_hp,
                attack=boosted_stats.attack,
                defense=boosted_stats.defense,
                speed=boosted_stats.speed,
                crit_chance=adjustments.player_crit_chance,
                crit_damage=boosted_stats.crit_damage,
                dodge=boosted_stats.dodge,
                hp_regeneration=boosted_stats.hp_regeneration,
            )

        # Combat avec attack du boss potentiellement enragé
        boss_as_mob = _boss_to_mob_definition(
            boss, overridden_attack=adjustments.boss_attack
        )
        battle_result = self.combat_service.fight_player_vs_mob(
            player_stats=boosted_stats, mob=boss_as_mob,
        )

        # Calcul des métriques de combat
        raw_damage_dealt = boss.current_hp - max(0, battle_result.mob_remaining_hp)
        # Application du damage_immunity_threshold sur le total infligé.
        # Note V1 : on filtre globalement, pas par coup. C'est une approximation
        # raisonnable pour le squelette ; raffinable plus tard en intégrant le
        # filter dans le tour-par-tour de CombatService.
        damage_dealt = self.modifier_service.filter_incoming_damage(
            raw_damage_dealt, adjustments.damage_immunity_threshold,
        )
        # damage_tanked = brut entrant total (avant réduction par défense),
        # cf. BattleResult.player_total_raw_damage_taken. Si l'attribut est
        # absent (anciens tests), fallback sur le calcul HP perdus.
        damage_tanked = getattr(
            battle_result, "player_total_raw_damage_taken", 0
        ) or (boosted_stats.max_hp - max(0, battle_result.player_remaining_hp))
        hp_healed = 0  # V1 solo

        # Persist (damage filtré, pas raw)
        self.world_boss_repository.apply_damage(boss.id, damage_dealt)
        self.world_boss_repository.add_combat_metrics(
            boss.id, profile.player.id,
            damage_dealt=damage_dealt,
            damage_tanked=damage_tanked,
            hp_healed=hp_healed,
        )

        # Quête hebdo : boss_damage (best effort)
        try:
            from app.infrastructure.db.repositories.weekly_quest_repository import (
                WeeklyQuestRepository,
            )
            session = self.world_boss_repository.session
            wqp_session = WeeklyQuestRepository(session)
            from app.application.use_cases.weekly_quests import (
                WeeklyQuestProgressService,
            )
            WeeklyQuestProgressService(wqp_session).on_boss_damage(
                profile.player.id, damage_dealt
            )
        except Exception:
            pass

        # Cooldown : prochaine fenêtre = minuit UTC
        next_avail = _next_midnight_utc(now)
        self.cooldown_repository.upsert(
            profile.player.id, BOSS_FIGHT_COOLDOWN_KEY, now, next_avail
        )

        boss_after = self.world_boss_repository.get_by_id(boss.id)
        defeated = boss_after.current_hp <= 0
        if defeated:
            self.world_boss_repository.mark_defeated(boss.id)

        msg_lines = [
            f"⚔️ Combat contre **{boss.name}** terminé.",
            f"💥 Dégâts infligés : **{damage_dealt:,}**",
            f"🛡️ Dégâts encaissés : **{damage_tanked:,}**",
            f"📊 PV restants du boss : **{boss_after.current_hp:,} / {boss.max_hp:,}**",
        ]
        if team_bonus_pct > 0:
            msg_lines.append(f"🤝 Bonus d'équipe appliqué : **+{team_bonus_pct}%**")
        if adjustments.enraged:
            msg_lines.append("🔥 **Boss enragé** — son attaque est amplifiée.")
        if (
            adjustments.damage_immunity_threshold > 0
            and raw_damage_dealt > 0
            and damage_dealt == 0
        ):
            msg_lines.append(
                f"🛡️ Carapace : vos coups (<{adjustments.damage_immunity_threshold}) "
                "ont glissé. Frappez plus fort."
            )
        if defeated:
            msg_lines.append(f"🏆 **{boss.name}** est vaincu !")

        return FightBossResult(
            success=True,
            message="\n".join(msg_lines),
            battle_result=battle_result,
            boss_remaining_hp=boss_after.current_hp,
            boss_max_hp=boss.max_hp,
            team_bonus_pct=team_bonus_pct,
            boss_defeated=defeated,
        )


# ---------- 4. Reward distribution on boss defeat ----------


@dataclass
class BossRewardEntry:
    player_id: int
    display_name: str
    role: str  # "top_damage" | "top_tank" | "top_heal" | "participant"
    gold: int
    xp: int
    items: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class CompleteBossResult:
    success: bool
    message: str
    rewards: list[BossRewardEntry] = field(default_factory=list)


class CompleteWorldBossUseCase:
    """Distribue les récompenses à tous les participants d'un boss vaincu.

    Règles spec :
        • Top damage / top tank / top heal reçoivent un bonus catégorie
        • Tous les participants reçoivent une récompense de base
        • Le top-X reçoit AUSSI la récompense de base ("récompense de base
          supplémentaire pour ceux qui ont déjà eu des bonus")

    Récompenses V1 (génériques, à affiner) :
        • Top damage / tank / heal : +200g, +100xp, +1 potion_soin_iii
        • Base (tous) : +50g, +25xp, +1 potion_soin_i
    """

    BASE_REWARD_GOLD = 50
    BASE_REWARD_XP = 25
    BASE_REWARD_ITEM = ("potion_soin_i", 1)

    TOP_REWARD_GOLD = 200
    TOP_REWARD_XP = 100
    TOP_REWARD_ITEM = ("potion_soin_iii", 1)

    def __init__(
        self,
        world_boss_repository: WorldBossRepository,
        player_repository: PlayerRepository,
        item_repository: ItemRepository,
        inventory_repository: InventoryRepository,
        progression_service: ProgressionService | None = None,
    ) -> None:
        self.world_boss_repository = world_boss_repository
        self.player_repository = player_repository
        self.item_repository = item_repository
        self.inventory_repository = inventory_repository
        self.progression_service = progression_service or ProgressionService()

    def execute(self, boss_id: int) -> CompleteBossResult:
        boss = self.world_boss_repository.get_by_id(boss_id)
        if boss is None:
            return CompleteBossResult(False, "❌ Boss introuvable.")

        participations = self.world_boss_repository.list_participations_with_metrics(boss_id)
        if not participations:
            return CompleteBossResult(
                False, "⚠️ Aucun participant à récompenser.", rewards=[],
            )

        # Identifier les top par métrique
        top_damage = max(participations, key=lambda p: p.damage_dealt)
        top_tank = max(participations, key=lambda p: p.damage_tanked)
        # heal=0 en V1 mais on garde la mécanique pour quand on aura un mode équipe
        top_heal = max(participations, key=lambda p: p.hp_healed)

        top_damage_id = top_damage.player_id if top_damage.damage_dealt > 0 else None
        top_tank_id = top_tank.player_id if top_tank.damage_tanked > 0 else None
        top_heal_id = top_heal.player_id if top_heal.hp_healed > 0 else None

        rewards: list[BossRewardEntry] = []
        for p in participations:
            profile = self.player_repository.get_profile_by_player_id(p.player_id)
            if profile is None:
                continue

            # Cumul des récompenses : base toujours, + bonus si top-X
            total_gold = self.BASE_REWARD_GOLD
            total_xp = self.BASE_REWARD_XP
            items: list[tuple[str, int]] = [self.BASE_REWARD_ITEM]
            roles_won: list[str] = []

            if p.player_id == top_damage_id:
                total_gold += self.TOP_REWARD_GOLD
                total_xp += self.TOP_REWARD_XP
                items.append(self.TOP_REWARD_ITEM)
                roles_won.append("top_damage")
            if p.player_id == top_tank_id:
                total_gold += self.TOP_REWARD_GOLD
                total_xp += self.TOP_REWARD_XP
                items.append(self.TOP_REWARD_ITEM)
                roles_won.append("top_tank")
            if p.player_id == top_heal_id:
                total_gold += self.TOP_REWARD_GOLD
                total_xp += self.TOP_REWARD_XP
                items.append(self.TOP_REWARD_ITEM)
                roles_won.append("top_heal")

            role = roles_won[0] if roles_won else "participant"

            # Application en DB
            self.player_repository.add_gold(p.player_id, total_gold)
            # XP avec calcul de level-up correct (sinon l'XP est juste
            # ajoutée mais le joueur ne gagne pas de niveau ni de skill points)
            new_level, new_xp, new_skill_points = self.progression_service.apply_level_up(
                current_level=profile.progression.level,
                current_xp=profile.progression.xp,
                gained_xp=total_xp,
                current_skill_points=profile.progression.skill_points,
            )
            self.player_repository.apply_progression(
                player_id=p.player_id,
                new_level=new_level,
                new_xp=new_xp,
                new_skill_points=new_skill_points,
            )
            for item_code, qty in items:
                item = self.item_repository.get_by_code(item_code)
                if item is not None:
                    self.inventory_repository.add_item(p.player_id, item.id, qty)

            rewards.append(
                BossRewardEntry(
                    player_id=p.player_id,
                    display_name=profile.player.display_name,
                    role=role,
                    gold=total_gold,
                    xp=total_xp,
                    items=items,
                )
            )

        return CompleteBossResult(
            success=True,
            message=f"🏆 **{boss.name}** vaincu — {len(rewards)} participant(s) récompensé(s).",
            rewards=rewards,
        )
