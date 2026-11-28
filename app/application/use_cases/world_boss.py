"""Use cases du système de world boss.

Use cases regroupés pour cohérence :
    1. SpawnWorldBossUseCase — spawn manuel à partir d'une BossDefinition (JSON)
    2. SpawnRandomWorldBossUseCase — auto-spawn pondéré par spawn_weight
    3. JoinWorldBossUseCase — joueur s'inscrit à la session
    4. LeaveWorldBossUseCase — joueur se désinscrit (refus s'il a déjà combattu)
    5. VoteForFightWorldBossUseCase / LaunchPartyFightWorldBossUseCase — combat
       collectif (vote puis bataille de groupe) + application des modifiers
    6. CompleteWorldBossUseCase — récompenses à la défaite, ou au départ du
       boss s'il a survécu à sa semaine (au prorata des PV qu'on lui a retirés)

Convention HP/résultat : l'assaut passe par `PartyCombatService.fight_party_vs_mobs`
avec le boss, ses gardes, ses phases et son ultime (cf. `boss_assault`) ; les
PV du boss sont conservés d'un assaut à l'autre.
"""

import random
from app.shared.formatters import format_int
from dataclasses import dataclass
from datetime import datetime, UTC, timedelta
from zoneinfo import ZoneInfo

from app.domain.entities.boss_definition import BossDefinition
from app.domain.entities.world_boss import WorldBoss
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.world_boss_repository import WorldBossRepository
from app.infrastructure.world_boss.boss_definition_loader import (
    get_definition as get_boss_definition,
    pick_random_definition,
)
from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS, ELEMENT_LABELS
from app.application.use_cases.world_boss_rewards import (  # noqa: F401 — sortis le 28/11/2026
    BossRewardEntry,
    CompleteBossResult,
    CompleteWorldBossUseCase,
)
from app.application.use_cases.world_boss_fight import (  # noqa: F401 — sortis le 28/11/2026
    BOSS_FIGHT_COOLDOWN_KEY,
    BOSS_FIGHT_MAX_TURNS,
    LaunchPartyFightWorldBossUseCase,
    PartyFightBossResult,
)


BOSS_RESPAWN_COOLDOWN_DAYS = 7  # 7 jours après défaite avant un nouveau spawn


def _normalize_utc(dt: datetime) -> datetime:
    """SQLite renvoie des datetimes naïfs ; on assume UTC pour les comparaisons."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def roll_boss_element(
    definition: BossDefinition, rng: random.Random | None = None, element: str | None = None,
) -> str:
    """L'élément du boss pour CETTE apparition (11/11/2026, décision de
    l'auteur) : celui demandé par un admin, sinon celui qu'impose sa fiche
    (champ vide par défaut), sinon tiré au hasard parmi les 8 éléments — un
    même boss change d'élément d'une semaine à l'autre."""
    valid = [e.value for e in ALL_ELEMENTS]
    for chosen in (element, definition.element):
        if chosen and chosen in valid:
            return chosen
    return (rng or random).choice(valid)


def element_label(element: str) -> str:
    """« 🔥 Feu » (vide pour un boss neutre)."""
    if not element:
        return ""
    return f"{ELEMENT_EMOJIS.get(element, '')} {ELEMENT_LABELS.get(element, element)}".strip()


def _create_boss_from_definition(
    repo: WorldBossRepository, definition: BossDefinition, element: str = "",
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
        element=element,
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
    `app/infrastructure/content/boss_definitions.json` (relue dès qu'elle
    change). `element` : l'élément voulu (tests) ; sinon tiré au hasard.
    """

    def __init__(self, world_boss_repository: WorldBossRepository) -> None:
        self.world_boss_repository = world_boss_repository

    def execute(
        self, boss_code: str, element: str | None = None, rng: random.Random | None = None,
    ) -> SpawnBossResult:
        existing = self.world_boss_repository.get_active()
        if existing is not None:
            return SpawnBossResult(
                success=False,
                message=(
                    f"❌ Un world boss est déjà actif : **{existing.name}** "
                    f"({format_int(existing.current_hp)}/{format_int(existing.max_hp)} PV)."
                ),
            )

        definition = get_boss_definition(boss_code)
        if definition is None:
            return SpawnBossResult(
                success=False, message=f"❌ Boss `{boss_code}` introuvable."
            )

        boss = _create_boss_from_definition(
            self.world_boss_repository, definition, roll_boss_element(definition, rng, element))
        label = element_label(boss.element)
        return SpawnBossResult(
            success=True,
            message=(f"⚡ **{boss.name}**{f' ({label})' if label else ''} apparaît avec "
                     f"**{format_int(boss.max_hp)}** PV !"),
            boss=boss,
        )


@dataclass
class AutoSpawnDecision:
    spawned: bool
    reason: str
    boss: WorldBoss | None = None


class SpawnRandomWorldBossUseCase:
    """Spawn du RAID HEBDOMADAIRE : un rendez-vous, pas une loterie, et un boss
    à la mesure des joueurs actifs (`levels`, cf. boss_selection_service).

    Le world boss est l'événement de la semaine — il doit donc tomber à un
    moment PRÉVISIBLE autour duquel la communauté se rassemble, et non au
    hasard d'un tirage horaire (l'ancien comportement : 5 % par heure, ce qui
    rendait l'apparition imprévisible et empêchait de « préparer » le raid).

    Conditions de spawn :
        1. aucun boss actif ;
        2. on est le JOUR DE SPAWN (lundi par défaut), à partir de l'heure
           d'ouverture ;
        3. aucun boss n'a déjà été lancé pendant CETTE semaine ISO.

    Le boss reste ensuite en vie toute la semaine : chaque jour à 21 h, les
    inscrits l'attaquent ensemble et lui arrachent des PV définitivement (il ne
    régénère jamais), jusqu'à son départ la veille du raid suivant.
    `weekly=False` restaure l'ancien tirage aléatoire.
    """

    def __init__(
        self,
        world_boss_repository: WorldBossRepository,
        spawn_probability: float = 0.05,
        weekly: bool = True,
        spawn_weekday: int = 0,   # 0 = lundi
        spawn_hour: int = 12,     # heure d'ouverture du raid (UTC, ou de `timezone`)
        levels: list[int] | None = None,   # niveaux des joueurs actifs (None = pas de filtre)
        timezone: ZoneInfo | None = None,
    ) -> None:
        self.world_boss_repository = world_boss_repository
        self.spawn_probability = spawn_probability
        self.weekly = weekly
        self.spawn_weekday = spawn_weekday
        self.spawn_hour = spawn_hour
        self.levels = levels
        self.timezone = timezone

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

        if self.weekly:
            # `force` saute le RENDEZ-VOUS (pour tester / lancer à la main)…
            local = now.astimezone(self.timezone) if self.timezone else now
            if not force and (
                local.weekday() != self.spawn_weekday or local.hour < self.spawn_hour
            ):
                return AutoSpawnDecision(False, "hors_fenetre_hebdo")
            # …mais JAMAIS la garde anti-double-raid : un seul raid par semaine
            # ISO, sinon un boss tué le lundi en relancerait un aussitôt.
            last = self.world_boss_repository.get_latest_defeated()
            if last is not None:
                spawned = _normalize_utc(last.spawned_at)
                if spawned.isocalendar()[:2] == now.isocalendar()[:2]:
                    return AutoSpawnDecision(False, "raid_deja_lance_cette_semaine")
        else:
            # Mode historique : cooldown 7j (opposable même en force) + tirage.
            last_defeated = self.world_boss_repository.get_latest_defeated()
            if last_defeated is not None:
                elapsed = now - _normalize_utc(last_defeated.defeated_at)
                if elapsed < timedelta(days=BOSS_RESPAWN_COOLDOWN_DAYS):
                    return AutoSpawnDecision(
                        False, f"cooldown_respawn ({elapsed.days}j sur 7j)"
                    )
            if not force and rng.random() > self.spawn_probability:
                return AutoSpawnDecision(False, "tirage_negatif")

        # À la mesure du serveur, et pas deux fois de suite le même.
        history = self.world_boss_repository.list_history(limit=1)
        definition = pick_random_definition(
            rng=rng, levels=self.levels, previous_code=history[0]["code"] if history else "")
        if definition is None:
            return AutoSpawnDecision(False, "serveur_pas_pret")

        boss = _create_boss_from_definition(
            self.world_boss_repository, definition, roll_boss_element(definition, rng))
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
            return JoinLeaveResult(False, "⚠️ Tu es déjà inscrit à ce raid.")

        self.world_boss_repository.upsert_participation(
            boss.id, profile.player.id, joined=True
        )
        count = self.world_boss_repository.count_joined(boss.id)
        word = "joueur" if count <= 1 else "joueurs"
        return JoinLeaveResult(
            True,
            f"✅ Tu rejoins le raid contre **{boss.name}** (raid à {count} {word}).",
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
            return JoinLeaveResult(False, "❌ Tu n'as pas de profil joueur.")

        existing = self.world_boss_repository.get_participation(boss.id, profile.player.id)
        if existing is None or not existing.joined:
            return JoinLeaveResult(False, "⚠️ Tu n'étais pas inscrit.")
        if existing.fights_count > 0:
            return JoinLeaveResult(
                False,
                "⚠️ Tu as déjà combattu ce boss : impossible de quitter le raid.",
            )

        self.world_boss_repository.upsert_participation(
            boss.id, profile.player.id, joined=False
        )
        return JoinLeaveResult(True, "🚪 Tu quittes le raid.")


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
            return VoteResult(False, "❌ Tu n'as pas de profil joueur.")

        participation = self.world_boss_repository.get_participation(
            boss.id, profile.player.id,
        )
        if participation is None or not participation.joined:
            return VoteResult(
                False, "❌ Rejoins d'abord le raid (🤝).",
            )

        if participation.voted_to_start:
            return VoteResult(
                False, "✅ Tu as déjà voté pour lancer le combat.",
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


# ---------- 3bis. Combat collectif (système de vote) ----------


# ---------- 4. Reward distribution on boss defeat ----------


