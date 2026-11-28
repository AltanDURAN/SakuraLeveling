"""Assaut quotidien d'un world boss par le groupe inscrit
(`LaunchPartyFightWorldBossUseCase`). Sorti de `world_boss.py` le 28/11/2026
(audit) : texte inchangé ; toujours importable depuis `world_boss`."""

from app.shared.formatters import format_int
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from zoneinfo import ZoneInfo

from app.application.services.player_stats_resolver import resolve_player_stats
from app.infrastructure.db.unit_of_work import transactional
from app.application.services.status_effect_resolver import resolve_regen_boosts
from app.domain.entities.world_boss import WorldBossParticipation
from app.domain.services.boss_modifier_service import BossModifierService
from app.domain.services.cooldown_service import CooldownService
from app.domain.services.stats_service import StatsService
from app.domain.services.world_boss_scaling_service import WorldBossScalingService
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.world_boss_repository import WorldBossRepository
from app.infrastructure.world_boss.boss_definition_loader import (
    get_definition as get_boss_definition,
)
from app.domain.services.monitoring import kinds
from app.infrastructure.monitoring.telemetry import record as record_event


BOSS_FIGHT_COOLDOWN_KEY = "world_boss_fight"


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
    # Pour la vidéo de l'assaut (cf. `boss_fight_video`) : le combat, les
    # ennemis dans l'ordre de la formation, le boss parmi eux, ses PV avant
    # l'assaut et les combattants (player_id, discord_id, name).
    battle: object | None = None
    enemies: list = field(default_factory=list)
    boss_index: int = 0
    boss_hp_before: int = 0
    fighters: list[dict] = field(default_factory=list)


class LaunchPartyFightWorldBossUseCase:
    """Lance un combat collectif entre tous les voteurs joined et le boss.

    Workflow :
    1. Liste les voteurs (joined=True ET voted_to_start=True)
    2. Filtre ceux qui ne sont plus en cooldown daily
    3. Pour chaque voteur : calcule stats (boost team + bonus skill + sets)
    4. Lance l'assaut (boss + gardes, cf. boss_assault)
    5. Distribue les métriques : damage_dealt/tanked/hp_healed per voteur
    6. Apply damage agrégé au boss + cooldown daily + joined=False par voteur
    7. Si boss tué → mark_defeated (le caller s'occupe de complete_boss)
    """

    def __init__(
        self,
        world_boss_repository: WorldBossRepository,
        player_repository: PlayerRepository,
        equipment_repository: EquipmentRepository,
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
        self.skill_allocation_repository = skill_allocation_repository
        self.cooldown_repository = cooldown_repository
        self.stats_service = stats_service
        self.scaling_service = scaling_service
        self.cooldown_service = cooldown_service
        self.modifier_service = modifier_service or BossModifierService()

    @transactional
    def execute(self, boss_id: int) -> PartyFightBossResult:
        from app.domain.services.party_combat_service import PartyCombatService
        from app.domain.services import element_service
        from app.domain.services.elemental_infusion_service import (
            ElementalInfusionService,
        )
        from app.infrastructure.db.repositories.element_affinity_repository import (
            ElementAffinityRepository,
        )
        from app.domain.services.mana_regeneration_service import ManaRegenerationService
        from app.application.services.combat_passives_resolver import resolve_party_passives
        from app.domain.services.combat_passives import outgoing_elemental_multiplier
        from app.infrastructure.db.repositories.player_mana_repository import (
            PlayerManaRepository,
        )

        boss = self.world_boss_repository.get_by_id(boss_id)
        if boss is None or not boss.is_alive:
            return PartyFightBossResult(False, "❌ Boss inactif.")

        # Combat quotidien : tous les INSCRITS (joined) participent (plus de
        # vote — le combat est déclenché par le scheduler à 21h).
        voters = self.world_boss_repository.list_joined_participants(boss_id)
        if not voters:
            return PartyFightBossResult(False, "❌ Aucun inscrit.")

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
        infused: dict[int, str] = {}
        fighters: list[dict] = []
        skill_loadouts: dict[int, list] = {}
        boss_aff = (
            element_service.single_element_affinities(boss.element)
            if boss.element else None
        )
        affinity_repo = ElementAffinityRepository(self.world_boss_repository.session)
        mana_repo = PlayerManaRepository(self.world_boss_repository.session)
        mana_regen_service = ManaRegenerationService()

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

        # Passifs de l'arbre (classes, Égide, Rempart…) et tactiques.
        passives_by_player, tactics_by_player = resolve_party_passives(
            self.world_boss_repository.session, [v.player_id for v in voters],
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
            # Chaîne de stats centralisée (skill + classe + sets + TITRES) —
            # corrige l'oubli des bonus de titre dans le combat de boss.
            # Élixirs d'Elna compris : le world boss est un combat de terrain.
            base_stats = resolve_player_stats(
                self.world_boss_repository.session,
                profile,
                equipped,
                stats_service=self.stats_service,
                elixirs=True,
            )
            boosted = self.scaling_service.apply_team_bonus(base_stats, num_joined)
            # Si crit immunity : neutralise crit_chance
            if adjustments.player_crit_chance == 0 and modifiers.get("crit_immunity"):
                # replace() garde TOUTES les stats (mana compris : invariant).
                from dataclasses import replace as _replace
                boosted = _replace(boosted, crit_chance=0)
            # Compétences équipées (slots libres, peuvent être vides) → passées
            # telles quelles au combat, qui les résout par tour.

            # Multiplicateurs élémentaires du voteur (si le boss a un élément).
            if boss_aff is not None:
                aff = affinity_repo.get_affinities(v.player_id)
                # L'ÉLÉMENT EST CHOISI TOUT SEUL, selon la faiblesse du boss
                # et la maîtrise du joueur (cf. ElementalInfusionService).
                infusion = ElementalInfusionService().best_for(
                    aff, boss_aff, affinity_repo.dead_elements(v.player_id),
                )
                if infusion.element:
                    infused[v.player_id] = infusion.element
                    elemental_out[v.player_id] = outgoing_elemental_multiplier(
                        infusion.multiplier, infusion.element, aff,
                        passives_by_player.get(v.player_id),
                    )
                elemental_in[v.player_id] = element_service.damage_multiplier(
                    boss.element, boss_aff, aff,
                )

            # Mana : ressource des compétences actives. On repart du mana
            # persisté, régénéré HORS combat jusqu'à maintenant (comme les PV
            # le seraient). Le mana ne se régénère PAS pendant le combat.
            mana_state = mana_repo.get_or_create(
                v.player_id, default_current_mana=boosted.mana_max,
            )
            regenerated_mana = mana_regen_service.apply_out_of_combat_regeneration(
                current_mana=mana_state.current_mana,
                mana_max=boosted.mana_max,
                mana_regeneration=boosted.mana_regeneration,
                last_updated_at=mana_state.updated_at,
                now=now,
                boosts=resolve_regen_boosts(self.world_boss_repository.session, v.player_id),
            )

            fighters.append({"player_id": v.player_id, "discord_id": profile.player.discord_id,
                             "name": profile.player.display_name})
            eligible.append((v, {
                "player_id": v.player_id,
                "user_id": v.player_id,  # fallback
                "name": profile.player.display_name,
                "avatar_url": "",
                "stats": boosted,
                "current_hp": boosted.max_hp,
                "max_hp": boosted.max_hp,
                "current_mana": regenerated_mana,
                "mana_max": boosted.mana_max,
            }))

        if not eligible:
            # Tous en cooldown — reset les votes pour laisser la place
            # à d'autres joueurs / un nouveau tour de vote.
            self.world_boss_repository.reset_votes_for_voters(boss_id)
            return PartyFightBossResult(
                False,
                "❌ Tous les inscrits ont déjà combattu aujourd'hui : l'assaut est annulé.",
                skipped_cooldown=skipped,
            )

        # Combat collectif : le boss, ses gardes, ses phases et son ultime
        # (cf. boss_assault — la même préparation que le calibrage).
        from app.domain.services.boss_assault import assault_enemies, boss_as_mob

        party = [payload for _, payload in eligible]
        enemies, boss_index = assault_enemies(
            boss_as_mob(boss, attack=adjustments.boss_attack),
            phases=boss_def.phases if boss_def is not None else [],
            ultimate=(boss_def.ultimate or None) if boss_def is not None else None,
            guards=boss_def.guards if boss_def is not None else [],
            # Modifiers boss dynamiques (le seuil d'immunité est appliqué par
            # coup dans la simulation, pas sur le total).
            immunity=adjustments.damage_immunity_threshold,
            heal_per_turn=int(modifiers.get("auto_heal_per_turn", 0)),
            reflect_pct=int(modifiers.get("reflect_pct", 0)),
            adds=modifiers.get("adds"),
            elemental_out=elemental_out, elemental_in=elemental_in, infusion=infused,
        )
        # Cartes à collectionner : la carte du boss, + dégâts contre lui et ses
        # gardes (seuls effets de carte au raid : les gardes portent des codes
        # de monstres, leurs cartes de monstre ne comptent pas ici).
        from app.application.use_cases.cards import player_card_bonuses
        from app.domain.services.card_service import with_card_bonuses
        from app.domain.services.title_bonus_service import TitleBonuses

        session = self.world_boss_repository.session
        card_titles = {
            payload["player_id"]: with_card_bonuses(
                TitleBonuses(), player_card_bonuses(session, payload["player_id"]), boss=True)
            for payload in party
        }
        battle_result = PartyCombatService().fight_party_vs_mobs(
            party, enemies,
            skill_loadouts_by_player=skill_loadouts,
            max_turns=BOSS_FIGHT_MAX_TURNS,
            passives_by_player=passives_by_player,
            tactics_by_player=tactics_by_player,
            title_bonuses_by_player=card_titles,
        )

        # Les PV restants du boss = résultat réel de la simulation (intègre
        # seuil d'immunité par coup + auto-soin). On synchronise l'instance
        # persistée dessus (peut remonter si le boss s'est soigné).
        contribs_by_id = {
            c.player_id: c for c in battle_result.contributions
        }
        boss_remaining = battle_result.enemies[boss_index]["remaining_hp"]
        damage_total = max(0, boss.current_hp - boss_remaining)
        self.world_boss_repository.set_current_hp(boss_id, boss_remaining)
        total_tanked = 0
        # Distribution des métriques par voteur
        for participation, _ in eligible:
            contrib = contribs_by_id.get(participation.player_id)
            if contrib is None:
                continue
            total_tanked += contrib.damage_tanked
            # Persiste le mana restant : il se régénérera hors combat.
            mana_repo.refresh_current_mana(participation.player_id, contrib.final_mana)
            record_event(self.world_boss_repository.session, kinds.BOSS_FIGHT,
                         player_id=participation.player_id, ref=boss.code,
                         data={"dmg": contrib.damage_dealt, "tank": contrib.damage_tanked,
                               "heal": contrib.hp_healed, "alive": bool(contrib.survived),
                               "n": len(eligible)})
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
                if contrib.hp_healed > 0:
                    _wqp.on_hp_healed(participation.player_id, contrib.hp_healed)
                    _dqp.on_hp_healed(participation.player_id, contrib.hp_healed)
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
            f"💥 Dégâts totaux : **{format_int(damage_total)}** "
            f"({format_int(total_tanked)} encaissés)\n"
            f"📊 PV restants du boss : **{format_int(boss_after.current_hp)} / {format_int(boss.max_hp)}**"
        )
        if skipped > 0:
            msg += f"\n_({skipped} inscrit(s) déjà passé(s) aujourd'hui : pas de second assaut.)_"
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
            battle=battle_result,
            enemies=enemies,
            boss_index=boss_index,
            boss_hp_before=boss.current_hp,
            fighters=fighters,
        )
