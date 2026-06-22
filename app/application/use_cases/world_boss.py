"""Use cases du système de world boss.

Use cases regroupés pour cohérence :
    1. SpawnWorldBossUseCase — spawn manuel à partir d'une BossDefinition (JSON)
    2. SpawnRandomWorldBossUseCase — auto-spawn pondéré par spawn_weight
    3. JoinWorldBossUseCase — joueur s'inscrit à la session
    4. LeaveWorldBossUseCase — joueur se désinscrit (refus s'il a déjà combattu)
    5. VoteForFightWorldBossUseCase / LaunchPartyFightWorldBossUseCase — combat
       collectif (vote puis bataille de groupe) + application des modifiers
    6. CompleteWorldBossUseCase — récompenses à la défaite

Convention HP/résultat : on réutilise `PartyCombatService.fight_party_vs_mob`
en wrappant le boss dans une `MobDefinition` éphémère.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from zoneinfo import ZoneInfo

from app.application.services.set_bonus_resolver import resolve_set_bonuses
from app.application.services.player_stats_resolver import resolve_player_stats
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
# Cap de tours d'un combat collectif : sécurité anti-boucle infinie quand
# l'auto-soin du boss dépasse les DPS de l'équipe (la journée n'aboutit alors
# ni à une mort ni à une victoire — le combat s'arrête simplement).
BOSS_FIGHT_MAX_TURNS = 4000
# Reset à minuit heure de Paris (CEST/CET selon saison, DST géré
# automatiquement par zoneinfo). Stocké en UTC.
_PARIS = ZoneInfo("Europe/Paris")


def _next_midnight_utc(now: datetime) -> datetime:
    """Prochain minuit heure de Paris (DST géré), reconverti en UTC."""
    now_aware = (
        now.astimezone(UTC) if now.tzinfo is not None
        else now.replace(tzinfo=UTC)
    )
    now_paris = now_aware.astimezone(_PARIS)
    tomorrow_paris = (now_paris + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return tomorrow_paris.astimezone(UTC)


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
        element=definition.element,
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


# ---------- 2.5 Vote ----------


@dataclass
class VoteResult:
    success: bool
    message: str
    votes: int = 0
    total: int = 0
    should_launch: bool = False
    boss_id: int | None = None


class VoteForFightWorldBossUseCase:
    """Marque le participant comme ayant voté pour lancer le combat.

    Le combat se lance automatiquement (par le caller) lorsque
    `should_launch=True` — c'est-à-dire dès que tous les `joined` ont
    voté `voted_to_start=True` (unanimité requise).
    """

    def __init__(
        self,
        world_boss_repository: WorldBossRepository,
        player_repository: PlayerRepository,
    ) -> None:
        self.world_boss_repository = world_boss_repository
        self.player_repository = player_repository

    def execute(self, discord_id: int) -> VoteResult:
        boss = self.world_boss_repository.get_active()
        if boss is None or not boss.is_alive:
            return VoteResult(False, "❌ Aucun world boss actif.")

        profile = self.player_repository.get_by_discord_id(discord_id)
        if profile is None:
            return VoteResult(False, "❌ Vous n'avez pas de profil joueur.")

        participation = self.world_boss_repository.get_participation(
            boss.id, profile.player.id,
        )
        if participation is None or not participation.joined:
            return VoteResult(
                False, "❌ Vous devez d'abord rejoindre le raid (🤝).",
            )

        if participation.voted_to_start:
            return VoteResult(
                False, "✅ Vous avez déjà voté pour lancer le combat.",
                votes=self.world_boss_repository.count_voted(boss.id),
                total=self.world_boss_repository.count_joined(boss.id),
                boss_id=boss.id,
            )

        self.world_boss_repository.set_voted(
            boss.id, profile.player.id, voted=True,
        )
        votes = self.world_boss_repository.count_voted(boss.id)
        total = self.world_boss_repository.count_joined(boss.id)
        should_launch = total > 0 and votes >= total
        msg = (
            f"🗳️ Vote enregistré : **{votes}/{total}**."
            + ("  Combat lancé !" if should_launch else "")
        )
        return VoteResult(
            True, msg, votes=votes, total=total,
            should_launch=should_launch, boss_id=boss.id,
        )


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


# ---------- 3bis. Combat collectif (système de vote) ----------


@dataclass
class PartyFightBossResult:
    success: bool
    message: str
    total_damage_dealt: int = 0
    total_damage_tanked: int = 0
    boss_remaining_hp: int = 0
    boss_max_hp: int = 0
    boss_defeated: bool = False
    voter_count: int = 0
    skipped_cooldown: int = 0


class LaunchPartyFightWorldBossUseCase:
    """Lance un combat collectif entre tous les voteurs joined et le boss.

    Workflow :
    1. Liste les voteurs (joined=True ET voted_to_start=True)
    2. Filtre ceux qui ne sont plus en cooldown daily
    3. Pour chaque voteur : calcule stats (boost team + bonus skill + sets)
    4. Lance PartyCombatService.fight_party_vs_mob
    5. Distribue les métriques : damage_dealt/tanked/hp_healed per voteur
    6. Apply damage agrégé au boss + cooldown daily + joined=False par voteur
    7. Si boss tué → mark_defeated (le caller s'occupe de complete_boss)
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
        self.cooldown_service = cooldown_service
        self.modifier_service = modifier_service or BossModifierService()

    def execute(self, boss_id: int) -> PartyFightBossResult:
        from app.domain.services.party_combat_service import PartyCombatService
        from app.domain.services import element_service
        from app.domain.services.skill_effect_service import offensive_element
        from app.infrastructure.elements import element_skill_loader
        from app.infrastructure.db.repositories.element_affinity_repository import (
            ElementAffinityRepository,
        )

        boss = self.world_boss_repository.get_by_id(boss_id)
        if boss is None or not boss.is_alive:
            return PartyFightBossResult(False, "❌ Boss inactif.")

        voters = self.world_boss_repository.list_voters(boss_id)
        if not voters:
            return PartyFightBossResult(False, "❌ Aucun voteur.")

        now = datetime.now(UTC)
        eligible: list[tuple[WorldBossParticipation, dict]] = []
        skipped = 0
        num_joined = self.world_boss_repository.count_joined(boss_id)

        # Système élémentaire : multiplicateurs ±50% par voteur.
        #   elemental_out : avantage du voteur sur le boss (dégâts infligés)
        #   elemental_in  : avantage du boss sur le voteur (dégâts subis)
        # Neutres (vides) si le boss n'a pas d'élément.
        elemental_out: dict[int, float] = {}
        elemental_in: dict[int, float] = {}
        skill_loadouts: dict[int, list] = {}
        boss_aff = (
            element_service.single_element_affinities(boss.element)
            if boss.element else None
        )
        affinity_repo = ElementAffinityRepository(self.world_boss_repository.session)

        # Modifiers du boss (immunity threshold, enrage, crit immunity)
        boss_def = get_boss_definition(boss.code)
        modifiers = boss_def.modifiers if boss_def is not None else {}
        adjustments = self.modifier_service.compute_adjustments(
            modifiers=modifiers,
            boss_max_hp=boss.max_hp,
            boss_current_hp=boss.current_hp,
            boss_attack=boss.attack,
            player_crit_chance=0,  # spécifique par voteur, on recalcule plus bas
        )

        for v in voters:
            # Cooldown daily
            cd = self.cooldown_repository.get_by_player_and_action(
                v.player_id, BOSS_FIGHT_COOLDOWN_KEY,
            )
            if not self.cooldown_service.is_available(cd, now):
                skipped += 1
                continue

            profile = self.player_repository.get_profile_by_player_id(v.player_id)
            if profile is None:
                continue
            equipped = self.equipment_repository.list_by_player_id(v.player_id)
            active_class = self.class_repository.get_current_class_for_player(v.player_id)
            # Chaîne de stats centralisée (skill + classe + sets + TITRES) —
            # corrige l'oubli des bonus de titre dans le combat de boss.
            base_stats = resolve_player_stats(
                self.world_boss_repository.session,
                profile,
                equipped,
                active_class,
                stats_service=self.stats_service,
            )
            boosted = self.scaling_service.apply_team_bonus(base_stats, num_joined)
            # Si crit immunity : neutralise crit_chance
            if adjustments.player_crit_chance == 0 and modifiers.get("crit_immunity"):
                boosted = type(boosted)(
                    max_hp=boosted.max_hp, attack=boosted.attack,
                    defense=boosted.defense, speed=boosted.speed,
                    crit_chance=0, crit_damage=boosted.crit_damage,
                    dodge=boosted.dodge, hp_regeneration=boosted.hp_regeneration,
                )
            # Compétences équipées (slots libres, peuvent être vides) → passées
            # telles quelles au combat, qui les résout par tour.
            equipped_skills = [
                element_skill_loader.get_skill(code)
                for code in (profile.player.skill_slot_1, profile.player.skill_slot_2)
                if code
            ]
            if equipped_skills:
                skill_loadouts[v.player_id] = equipped_skills

            # Multiplicateurs élémentaires du voteur (si le boss a un élément).
            if boss_aff is not None:
                aff = affinity_repo.get_affinities(v.player_id)
                # élément d'attaque = compétence offensive équipée, sinon repli
                # sur l'affinité la plus haute (le joueur frappe quand même).
                player_elem = offensive_element(equipped_skills) or (
                    max(aff, key=aff.get) if aff else ""
                )
                if player_elem:
                    elemental_out[v.player_id] = element_service.damage_multiplier(
                        player_elem, aff, boss_aff,
                    )
                elemental_in[v.player_id] = element_service.damage_multiplier(
                    boss.element, boss_aff, aff,
                )

            eligible.append((v, {
                "player_id": v.player_id,
                "user_id": v.player_id,  # fallback
                "name": profile.player.display_name,
                "avatar_url": "",
                "stats": boosted,
                "current_hp": boosted.max_hp,
                "max_hp": boosted.max_hp,
            }))

        if not eligible:
            # Tous en cooldown — reset les votes pour laisser la place
            # à d'autres joueurs / un nouveau tour de vote.
            self.world_boss_repository.reset_votes_for_voters(boss_id)
            return PartyFightBossResult(
                False,
                "❌ Tous les voteurs ont déjà combattu aujourd'hui — votes annulés.",
                skipped_cooldown=skipped,
            )

        # Combat collectif
        boss_as_mob = _boss_to_mob_definition(
            boss, overridden_attack=adjustments.boss_attack,
        )
        party = [payload for _, payload in eligible]
        battle_result = PartyCombatService().fight_party_vs_mob(
            party=party, mob=boss_as_mob,
            elemental_mult_by_player=elemental_out,
            incoming_elemental_mult_by_player=elemental_in,
            skill_loadouts_by_player=skill_loadouts,
            # Modifiers boss dynamiques (le seuil d'immunité est désormais
            # appliqué par coup dans la simulation, pas sur le total).
            damage_immunity_threshold=adjustments.damage_immunity_threshold,
            boss_heal_per_turn=int(modifiers.get("auto_heal_per_turn", 0)),
            boss_reflect_pct=int(modifiers.get("reflect_pct", 0)),
            boss_adds=modifiers.get("adds"),
            max_turns=BOSS_FIGHT_MAX_TURNS,
        )

        # Les PV restants du boss = résultat réel de la simulation (intègre
        # seuil d'immunité par coup + auto-soin). On synchronise l'instance
        # persistée dessus (peut remonter si le boss s'est soigné).
        contribs_by_id = {
            c.player_id: c for c in battle_result.contributions
        }
        damage_total = max(0, boss.current_hp - battle_result.mob_remaining_hp)
        self.world_boss_repository.set_current_hp(
            boss_id, battle_result.mob_remaining_hp,
        )
        total_tanked = 0
        # Distribution des métriques par voteur
        for participation, _ in eligible:
            contrib = contribs_by_id.get(participation.player_id)
            if contrib is None:
                continue
            total_tanked += contrib.damage_tanked
            self.world_boss_repository.add_combat_metrics(
                boss_id, participation.player_id,
                damage_dealt=contrib.damage_dealt,
                damage_tanked=contrib.damage_tanked,
                hp_healed=contrib.hp_healed,
            )
            # Pose cooldown daily
            next_avail = _next_midnight_utc(now)
            self.cooldown_repository.upsert(
                participation.player_id, BOSS_FIGHT_COOLDOWN_KEY, now, next_avail,
            )
            # Quêtes : on_damage_dealt + on_damage_tanked
            try:
                from app.application.use_cases.weekly_quests import (
                    WeeklyQuestProgressService,
                )
                from app.application.use_cases.daily_quests import (
                    DailyQuestProgressService,
                )
                from app.infrastructure.db.repositories.weekly_quest_repository import (
                    WeeklyQuestRepository,
                )
                from app.infrastructure.db.repositories.daily_quest_repository import (
                    DailyQuestRepository,
                )
                session = self.world_boss_repository.session
                _wqp = WeeklyQuestProgressService(WeeklyQuestRepository(session))
                _dqp = DailyQuestProgressService(DailyQuestRepository(session))
                if contrib.damage_dealt > 0:
                    _wqp.on_damage_dealt(participation.player_id, contrib.damage_dealt)
                    _dqp.on_damage_dealt(participation.player_id, contrib.damage_dealt)
                if contrib.damage_tanked > 0:
                    _wqp.on_damage_tanked(participation.player_id, contrib.damage_tanked)
                    _dqp.on_damage_tanked(participation.player_id, contrib.damage_tanked)
            except Exception as _e:
                import logging
                logging.getLogger(__name__).warning(
                    "Quest hook (party boss) failed: %s", _e, exc_info=True,
                )
            # Retire de la file (joined=False) et reset vote
            self.world_boss_repository.upsert_participation(
                boss_id, participation.player_id, joined=False,
            )
            self.world_boss_repository.set_voted(
                boss_id, participation.player_id, voted=False,
            )

        # Reset votes des éventuels non-voteurs restés joined (au cas où)
        self.world_boss_repository.reset_votes_for_voters(boss_id)

        boss_after = self.world_boss_repository.get_by_id(boss_id)
        defeated = boss_after.current_hp <= 0
        if defeated:
            self.world_boss_repository.mark_defeated(boss_id)

        msg = (
            f"⚔️ Raid collectif contre **{boss.name}** terminé "
            f"({len(eligible)} combattants).\n"
            f"💥 Dégâts totaux : **{damage_total:,}** "
            f"({total_tanked:,} encaissés)\n"
            f"📊 PV restants du boss : **{boss_after.current_hp:,} / {boss.max_hp:,}**"
        )
        if skipped > 0:
            msg += f"\n_({skipped} voteur(s) ignoré(s) — déjà combattu(s) aujourd'hui.)_"
        if defeated:
            msg += f"\n🏆 **{boss.name}** est vaincu !"

        return PartyFightBossResult(
            success=True,
            message=msg,
            total_damage_dealt=damage_total,
            total_damage_tanked=total_tanked,
            boss_remaining_hp=boss_after.current_hp,
            boss_max_hp=boss.max_hp,
            boss_defeated=defeated,
            voter_count=len(eligible),
            skipped_cooldown=skipped,
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
