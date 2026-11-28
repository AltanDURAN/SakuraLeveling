from dataclasses import replace
from datetime import datetime, UTC

from app.application.services.elemental_resolver import elemental_multipliers
from app.application.services.encounter_participant import EncounterParticipant
from app.application.services.set_bonus_resolver import resolve_set_bonuses
from app.application.services.status_effect_resolver import (
    resolve_regen_boosts,
    resolve_status_effects,
)
from app.application.services.title_bonus_resolver import resolve_title_bonuses
from app.domain.services.health_regeneration_service import HealthRegenerationService
from app.domain.services.mana_regeneration_service import ManaRegenerationService
from app.domain.services.title_bonus_service import TitleBonusService
from app.domain.services.mob_ability_service import (
    ELITE_LABEL,
    get_mob_abilities,
    is_group_elite,
)
from app.domain.services.party_combat_service import EnemySetup, PartyCombatService
from app.domain.services.power_score_service import PowerScoreService
from app.domain.services.skill_tree_service import SkillTreeService
from app.domain.services.stats_service import StatsService
from app.domain.value_objects.stats import Stats
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_health_repository import PlayerHealthRepository
from app.infrastructure.db.repositories.player_mana_repository import PlayerManaRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.player_title_repository import PlayerTitleRepository
from app.infrastructure.db.session import get_db_session
from app.application.use_cases.cards import player_card_bonuses
from app.domain.services.card_service import with_card_bonuses
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)
from app.infrastructure.titles.title_loader import (
    get_definition as get_title_def,
)
from app.application.services.encounter_rewards import EncounterRewardsMixin


class EncounterService(EncounterRewardsMixin):
    def get_regenerated_player_hp(
        self,
        player_id: int,
        max_hp: int,
        hp_regeneration: int,
    ) -> int:
        with get_db_session() as session:
            return self._regenerated_hp(session, player_id, max_hp, hp_regeneration)

    @staticmethod
    def _ko_message(player_id: int, hp_regeneration: int) -> str:
        """K.O. : dire QUAND le joueur pourra se battre (les PV remontent
        chaque minute pleine hors combat), plutôt que « bois une potion »."""
        if hp_regeneration > 0:
            with get_db_session() as session:
                state = PlayerHealthRepository(session).get_by_player_id(player_id)
            if state is not None:
                since = state.updated_at
                if since.tzinfo is None:
                    since = since.replace(tzinfo=UTC)
                elapsed = max(0.0, (datetime.now(UTC) - since).total_seconds())
                ready_at = since.timestamp() + (int(elapsed // 60) + 1) * 60
                return (f"💀 Tu es K.O. : tu pourras combattre à <t:{int(ready_at)}:T> "
                        "(<t:%d:R>), tes PV remontent seuls hors combat." % int(ready_at))
        return ("💀 Tu es K.O. : tes PV ne remontent pas tout seuls. "
                "Une potion (`/utiliser`) te remet debout.")

    @staticmethod
    def _regenerated_hp(session, player_id: int, max_hp: int, hp_regeneration: int) -> int:
        """PV du joueur à cet instant, régénération hors combat comprise."""
        player_health_repository = PlayerHealthRepository(session)

        health_state = player_health_repository.get_or_create(
            player_id=player_id,
            default_current_hp=max_hp,
        )

        regenerated_current_hp = HealthRegenerationService().apply_out_of_combat_regeneration(
            current_hp=health_state.current_hp,
            max_hp=max_hp,
            hp_regeneration=hp_regeneration,
            last_updated_at=health_state.updated_at,
            now=datetime.now(UTC),
            boosts=resolve_regen_boosts(session, player_id),
        )

        if regenerated_current_hp != health_state.current_hp:
            player_health_repository.refresh_current_hp(
                player_id=player_id,
                new_current_hp=regenerated_current_hp,
            )

        return regenerated_current_hp

    def register_participant(
        self,
        encounter,
        user_id: int,
        display_name: str,
        avatar_url: str,
    ) -> tuple[bool, str]:
        if encounter is None:
            return False, "Aucun combat à rejoindre."

        if getattr(encounter, "resolved", False):
            return False, "Ce combat a déjà commencé."

        if user_id in encounter.participants:
            return False, "Tu as déjà rejoint le combat."

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            equipment_repository = EquipmentRepository(session)
            skill_allocation_repository = PlayerSkillAllocationRepository(session)

            profile = player_repository.get_by_discord_id(user_id)
            if profile is None:
                return False, "Ton profil n'existe pas encore : commence par /tuto."

            equipped_items = equipment_repository.list_by_player_id(profile.player.id)
            allocations = skill_allocation_repository.list_by_player(profile.player.id)
            skill_bonuses = SkillTreeService(get_skill_tree_definition()).aggregate_bonuses(
                allocations
            )

            title_bonuses = resolve_title_bonuses(session, profile.player.id)
            set_bonuses = resolve_set_bonuses(equipped_items, profile.player.panoplie_bonus)
            status_bonuses = resolve_status_effects(session, profile.player.id)

            stats = StatsService().calculate_player_stats(
                profile=profile,
                equipped_items=equipped_items,
                skill_bonuses=skill_bonuses,
                title_bonuses=title_bonuses,
                set_bonuses=set_bonuses,
                status_bonuses=status_bonuses,
            )
            # Stats de COMBAT : élixirs d'Elna compris (ils comptent ici). Les
            # PV stockés restent ceux du socle sans élixir, cf. resolve.
            combat_stats = StatsService().calculate_player_stats(
                profile=profile,
                equipped_items=equipped_items,
                skill_bonuses=skill_bonuses,
                title_bonuses=title_bonuses,
                set_bonuses=set_bonuses,
                status_bonuses=resolve_status_effects(session, profile.player.id, elixirs=True),
            )

        regenerated_current_hp = self.get_regenerated_player_hp(
            player_id=profile.player.id,
            max_hp=stats.max_hp,
            hp_regeneration=stats.hp_regeneration,
        )

        # K.O. : on ne rejoint pas un combat à 0 PV. Sans ce verrou, un joueur
        # à terre rejoignait, mourait au premier coup et touchait quand même
        # l'XP pleine (les morts la reçoivent) sans avoir combattu.
        if regenerated_current_hp <= 0:
            return False, self._ko_message(profile.player.id, stats.hp_regeneration)

        participant = EncounterParticipant(
            user_id=user_id,
            player_id=profile.player.id,
            display_name=display_name,
            avatar_url=avatar_url,
            current_hp=regenerated_current_hp,
            max_hp=stats.max_hp,
            stats=stats,
            level=profile.progression.level,
        )

        encounter.participants[user_id] = participant

        return True, "Tu as rejoint le combat." + self._danger_note(
            encounter, combat_stats, self._scaled_hp(regenerated_current_hp, stats.max_hp, combat_stats.max_hp),
        )

    @staticmethod
    def _scaled_hp(current_hp: int, from_max: int, to_max: int) -> int:
        """PV ramenés d'un maximum à l'autre en gardant la PROPORTION :
        l'élixir de vitalité grandit les PV max le temps du combat, les PV
        stockés restent comptés sur le maximum sans élixir."""
        if from_max <= 0 or from_max == to_max:
            return current_hp
        return max(0, min(to_max, round(current_hp * to_max / from_max)))

    @staticmethod
    def _danger_note(encounter, stats: Stats, current_hp: int) -> str:
        """Avertissement personnel quand le combat est déséquilibré.

        Une zone couvre une large plage de niveaux et le monstre est tiré sans
        regarder qui va le combattre : un débutant peut tomber sur un monstre
        prévu pour le niveau 30. La puissance affichée sur l'image (« 1K ») ne
        lui dit rien — on la compare donc à la sienne."""
        mob = encounter.mob_state
        mobs = list(getattr(encounter, "mobs", None) or [mob])
        power = PowerScoreService()
        # Une meute : la puissance de ses monstres additionnée (ils frappent
        # tous en même temps).
        mob_power = sum(power.calculate_from_stats(Stats(
            max_hp=m.max_hp, attack=m.attack, defense=m.defense,
            speed=m.speed, crit_chance=m.crit_chance, crit_damage=m.crit_damage,
            dodge=m.dodge, hp_regeneration=0,
        )) for m in mobs)
        name = mob.name if len(mobs) == 1 else f"la meute ({len(mobs)} monstres)"
        strong = "puissant" if len(mobs) == 1 else "puissante"
        player_power = power.calculate_from_stats(stats)
        ratio = mob_power / max(1, player_power)
        notes = []
        if ratio >= 2:
            notes.append(
                f"💀 **Très dangereux** : {name} est environ **{ratio:.0f}×** plus "
                f"{strong} que toi ({power.format_score(mob_power)} contre "
                f"{power.format_score(player_power)}). Sans alliés, tu risques le K.O."
            )
        elif ratio >= 1.2:
            notes.append(
                f"⚠️ **Risqué** : {name} est plus {strong} que toi "
                f"({power.format_score(mob_power)} contre {power.format_score(player_power)})."
            )
        if is_group_elite(getattr(mob, "code", None)):
            notes.append(ELITE_LABEL)
        if stats.max_hp and current_hp < 0.3 * stats.max_hp:
            notes.append(f"❤️ Attention, il ne te reste que **{current_hp} / {stats.max_hp}** PV.")
        return ("\n" + "\n".join(notes)) if notes else ""

    def resolve_active_encounter(self, encounter):
        if encounter is None:
            return None

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            equipment_repository = EquipmentRepository(session)
            mob_repository = MobRepository(session)
            skill_allocation_repository = PlayerSkillAllocationRepository(session)
            skill_tree_service = SkillTreeService(get_skill_tree_definition())
            title_repo = PlayerTitleRepository(session)
            title_bonus_service = TitleBonusService()

            mob = mob_repository.get_by_code(encounter.mob_state.code)
            if mob is None:
                return None

            from app.application.services.combat_passives_resolver import (
                resolve_party_passives,
            )

            party = []
            fallen: list[int] = []
            title_bonuses_by_player: dict = {}
            mana_repo = PlayerManaRepository(session)
            now = datetime.now(UTC)
            # Passifs de l'arbre (classes, Tenace, Égide…) et tactique de combat.
            passives_by_player, tactics_by_player = resolve_party_passives(
                session, [p.player_id for p in encounter.participants.values()],
            )

            for participant in encounter.participants.values():
                profile = player_repository.get_by_discord_id(participant.user_id)
                if profile is None:
                    continue

                equipped_items = equipment_repository.list_by_player_id(participant.player_id)
                allocations = skill_allocation_repository.list_by_player(participant.player_id)
                skill_bonuses = skill_tree_service.aggregate_bonuses(allocations)

                # Charger les définitions des titres débloqués pour agréger
                # les bonus passifs (vs famille du mob + Champion 1v1).
                title_codes = title_repo.list_codes_for_player(participant.player_id)
                title_defs = [
                    d for d in (get_title_def(code) for code in title_codes) if d is not None
                ]
                title_bonuses = title_bonus_service.aggregate(title_defs)
                # Cartes à collectionner : + dégâts contre CE monstre (zone seulement).
                title_bonuses_by_player[participant.player_id] = with_card_bonuses(
                    title_bonuses, player_card_bonuses(session, participant.player_id))

                set_bonuses = resolve_set_bonuses(equipped_items, profile.player.panoplie_bonus)
                # Élixirs d'Elna compris : un combat de zone est du terrain.
                status_bonuses = resolve_status_effects(session, participant.player_id, elixirs=True)

                stats = StatsService().calculate_player_stats(
                    profile=profile,
                    equipped_items=equipped_items,
                    skill_bonuses=skill_bonuses,
                    title_bonuses=title_bonuses,
                    set_bonuses=set_bonuses,
                    status_bonuses=status_bonuses,
                )
                # PV relus AU LANCEMENT, comptés sur le maximum sans élixir (celui
                # des PV stockés) : lus à l'inscription, ils perdaient la potion
                # bue et la régénération de l'attente (signalé par un testeur).
                base_stats = StatsService().calculate_player_stats(
                    profile=profile,
                    equipped_items=equipped_items,
                    skill_bonuses=skill_bonuses,
                    title_bonuses=title_bonuses,
                    set_bonuses=set_bonuses,
                    status_bonuses=resolve_status_effects(session, participant.player_id),
                )
                participant.max_hp = base_stats.max_hp
                participant.current_hp = self._regenerated_hp(
                    session, participant.player_id, base_stats.max_hp, base_stats.hp_regeneration)
                if participant.current_hp <= 0:
                    # Tombé ailleurs depuis son inscription : il ne combat pas.
                    fallen.append(participant.user_id)
                    continue

                # Mana courant (régénéré hors combat jusqu'à MAINTENANT) : les
                # compétences actives y puisent (cf. combat_passives.MANA_COSTS).
                # Persisté en fin de combat par `persist_final_players_hp`.
                mana_state = mana_repo.get_or_create(
                    participant.player_id, default_current_mana=stats.mana_max)
                current_mana = ManaRegenerationService().apply_out_of_combat_regeneration(
                    current_mana=mana_state.current_mana,
                    mana_max=stats.mana_max,
                    mana_regeneration=stats.mana_regeneration,
                    last_updated_at=mana_state.updated_at,
                    now=now,
                    boosts=resolve_regen_boosts(session, participant.player_id),
                )

                party.append(
                    {
                        "player_id": participant.player_id,
                        "user_id": participant.user_id,
                        "name": participant.display_name,
                        "avatar_url": participant.avatar_url,
                        "current_hp": self._scaled_hp(participant.current_hp, participant.max_hp, stats.max_hp),
                        "max_hp": stats.max_hp,
                        "current_mana": current_mana,
                        "mana_max": stats.mana_max,
                        "stats": stats,
                    }
                )

            # Ennemis : le monstre, ou chaque monstre de la meute (stats déjà
            # réduites au spawn, cf. pack_service). Système élémentaire ACTIF :
            # l'élément spawné de chacun contre les affinités de chaque joueur
            # (l'élément d'attaque est choisi tout seul, cf. elemental_resolver).
            states = list(getattr(encounter, "mobs", None) or [encounter.mob_state])
            enemies = []
            for state in states:
                definition = mob if state is encounter.mob_state else mob_repository.get_by_code(state.code)
                if definition is None:
                    continue
                if len(states) > 1:
                    definition = replace(definition, max_hp=state.max_hp, current_hp=state.max_hp,
                                         attack=state.attack)
                outgoing, incoming, infused = elemental_multipliers(
                    session, [m["player_id"] for m in party], state.element or "", passives_by_player)
                enemies.append(EnemySetup(mob=definition, abilities=get_mob_abilities(definition.code),
                                          elemental_out=outgoing, elemental_in=incoming,
                                          infusion=infused))

        for user_id in fallen:
            del encounter.participants[user_id]
        if not party:
            return None

        return PartyCombatService().fight_party_vs_mobs(
            party, enemies,
            title_bonuses_by_player=title_bonuses_by_player,
            passives_by_player=passives_by_player,
            tactics_by_player=tactics_by_player,
        )

    def persist_final_players_hp(self, result, encounter=None) -> None:
        """PV ET mana de fin de combat : ils remontent ensuite hors combat.
        Avec `encounter`, les PV sont ramenés au maximum SANS élixir de
        vitalité (celui des PV stockés), en gardant la proportion."""
        if not result.turn_logs:
            return
        base_max = {p.player_id: p.max_hp for p in (encounter.participants.values() if encounter else ())}

        final_turn = result.turn_logs[-1]
        final_players_state = final_turn.players_state

        with get_db_session(atomic=True) as session:
            player_health_repository = PlayerHealthRepository(session)
            mana_repo = PlayerManaRepository(session)

            for player_state in final_players_state:
                player_id = player_state["player_id"]

                current_hp = player_state["current_hp"]
                if player_id in base_max:
                    current_hp = self._scaled_hp(current_hp, player_state.get("max_hp", 0), base_max[player_id])
                player_health_repository.update_current_hp(
                    player_id=player_id,
                    current_hp=current_hp,
                )
                if "current_mana" in player_state:
                    mana_repo.get_or_create(player_id, default_current_mana=player_state["current_mana"])
                    mana_repo.update_current_mana(player_id, max(0, int(player_state["current_mana"])))


    def unregister_participant(
        self,
        encounter,
        user_id: int,
    ) -> tuple[bool, str]:
        if encounter is None:
            return False, "Aucun combat à quitter."

        if getattr(encounter, "resolved", False):
            return False, "Ce combat a déjà commencé."

        if user_id not in encounter.participants:
            return False, "Tu n'as pas rejoint ce combat."

        del encounter.participants[user_id]
        return True, "Tu as quitté le combat."