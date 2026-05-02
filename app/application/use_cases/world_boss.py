"""Use cases du système de world boss.

5 use cases regroupés pour cohérence :
    1. SpawnWorldBossUseCase — admin uniquement, V1 : boost ×100 d'un mob existant
    2. JoinWorldBossUseCase — joueur s'inscrit à la session
    3. LeaveWorldBossUseCase — joueur se désinscrit (refus s'il a déjà combattu)
    4. FightWorldBossUseCase — solo combat avec bonus d'équipe + cooldown 1/jour
    5. CompleteWorldBossUseCase — récompenses à la défaite

Convention HP/résultat : `PartyCombatService` étant orienté équipe vs mob,
on simule un combat 1v1 (1 joueur vs 1 boss) en réutilisant le
`CombatService.fight_player_vs_mob` qui prend `Stats` + `MobDefinition`.
On wrappe les stats du boss dans une `MobDefinition` éphémère (factory
pure, jamais persistée) pour rester compatible.
"""

from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta

from app.domain.entities.mob_definition import MobDefinition
from app.domain.entities.world_boss import WorldBoss, WorldBossParticipation
from app.domain.services.combat_service import CombatService
from app.domain.services.cooldown_service import CooldownService
from app.domain.services.skill_tree_service import SkillTreeService
from app.domain.services.stats_service import StatsService
from app.domain.services.world_boss_scaling_service import WorldBossScalingService
from app.domain.value_objects.battle_result import BattleResult
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.world_boss_repository import WorldBossRepository
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)


BOSS_FIGHT_COOLDOWN_KEY = "world_boss_fight"
BOSS_STAT_BOOST_FACTOR = 100  # V1 : boost ×100 du mob de base pour test
DAILY_RESET_HOUR_UTC = 0  # reset à minuit UTC


def _next_midnight_utc(now: datetime) -> datetime:
    tomorrow = (now + timedelta(days=1)).replace(
        hour=DAILY_RESET_HOUR_UTC, minute=0, second=0, microsecond=0
    )
    return tomorrow


def _boost_mob_to_boss_stats(mob: MobDefinition, factor: int) -> dict:
    return {
        "max_hp": mob.max_hp * factor,
        "attack": mob.attack * factor,
        "defense": mob.defense * factor,
        "speed": mob.speed,
        "crit_chance": mob.crit_chance,
        "crit_damage": mob.crit_damage,
        "dodge": mob.dodge,
        "hp_regeneration": 0,  # spec : un boss ne regagne JAMAIS de PV
    }


def _boss_to_mob_definition(boss: WorldBoss) -> MobDefinition:
    """Wrappe un WorldBoss en MobDefinition pour réutiliser CombatService."""
    return MobDefinition(
        id=-1,  # sentinel : pas en DB en tant que mob
        code=boss.code,
        name=boss.name,
        description="",
        image_name=boss.image_name,
        family="world_boss",
        max_hp=boss.max_hp,
        current_hp=boss.current_hp,
        attack=boss.attack,
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


# ---------- 1. Spawn ----------


@dataclass
class SpawnBossResult:
    success: bool
    message: str
    boss: WorldBoss | None = None


class SpawnWorldBossUseCase:
    """Spawn manuel d'un world boss à partir d'un mob existant boosté ×100.

    Refuse s'il y a déjà un boss actif. Pour V1, prend un mob_code existant
    en DB. Plus tard, prendra un boss_code dédié avec stats finement réglées.
    """

    def __init__(
        self,
        world_boss_repository: WorldBossRepository,
        mob_repository: MobRepository,
    ) -> None:
        self.world_boss_repository = world_boss_repository
        self.mob_repository = mob_repository

    def execute(self, mob_code: str, custom_name: str | None = None) -> SpawnBossResult:
        existing = self.world_boss_repository.get_active()
        if existing is not None:
            return SpawnBossResult(
                success=False,
                message=(
                    f"❌ Un world boss est déjà actif : **{existing.name}** "
                    f"({existing.current_hp:,}/{existing.max_hp:,} PV)."
                ),
            )

        mob = self.mob_repository.get_by_code(mob_code)
        if mob is None:
            return SpawnBossResult(
                success=False, message=f"❌ Mob `{mob_code}` introuvable."
            )

        boost = _boost_mob_to_boss_stats(mob, BOSS_STAT_BOOST_FACTOR)
        boss = self.world_boss_repository.create(
            code=f"boss_{mob.code}",
            name=custom_name or f"{mob.name} surpuissant",
            image_name=mob.image_name,
            max_hp=boost["max_hp"],
            attack=boost["attack"],
            defense=boost["defense"],
            speed=boost["speed"],
            crit_chance=boost["crit_chance"],
            crit_damage=boost["crit_damage"],
            dodge=boost["dodge"],
            hp_regeneration=boost["hp_regeneration"],
        )
        return SpawnBossResult(
            success=True,
            message=(
                f"⚡ **{boss.name}** apparaît avec **{boss.max_hp:,}** PV !"
            ),
            boss=boss,
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
        return JoinLeaveResult(
            True,
            f"✅ Vous rejoignez le raid contre **{boss.name}** (raid à {count} joueur(s)).",
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

        # Combat
        boss_as_mob = _boss_to_mob_definition(boss)
        battle_result = self.combat_service.fight_player_vs_mob(
            player_stats=boosted_stats, mob=boss_as_mob,
        )

        # Calcul des métriques de combat
        damage_dealt = boss.current_hp - max(0, battle_result.mob_remaining_hp)
        damage_tanked = boosted_stats.max_hp - max(0, battle_result.player_remaining_hp)
        # V1 : pas de heal (mode solo, pas de healer dédié)
        hp_healed = 0

        # Persist
        self.world_boss_repository.apply_damage(boss.id, damage_dealt)
        self.world_boss_repository.add_combat_metrics(
            boss.id, profile.player.id,
            damage_dealt=damage_dealt,
            damage_tanked=damage_tanked,
            hp_healed=hp_healed,
        )

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
    ) -> None:
        self.world_boss_repository = world_boss_repository
        self.player_repository = player_repository
        self.item_repository = item_repository
        self.inventory_repository = inventory_repository

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
            self.player_repository.add_xp(p.player_id, total_xp)
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
