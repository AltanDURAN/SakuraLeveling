from datetime import datetime, UTC

from app.bot.runtime.encounter_participant import EncounterParticipant
from app.domain.services.health_regeneration_service import HealthRegenerationService
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.services.stats_service import StatsService
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_health_repository import PlayerHealthRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session


class EncounterService:
    def get_regenerated_player_hp(
        self,
        player_id: int,
        max_hp: int,
        hp_regeneration: int,
    ) -> int:
        with get_db_session() as session:
            player_health_repository = PlayerHealthRepository(session)

            health_state = player_health_repository.get_or_create(
                player_id=player_id,
                default_current_hp=max_hp,
            )

            now = datetime.now(UTC)

            regenerated_current_hp = HealthRegenerationService().apply_out_of_combat_regeneration(
                current_hp=health_state.current_hp,
                max_hp=max_hp,
                hp_regeneration=hp_regeneration,
                last_updated_at=health_state.updated_at,
                now=now,
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

        if user_id in encounter.participants:
            return False, "Vous avez déjà rejoint le combat."

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            equipment_repository = EquipmentRepository(session)
            class_repository = ClassRepository(session)

            profile = player_repository.get_by_discord_id(user_id)
            if profile is None:
                return False, "Votre profil joueur n'existe pas encore. Utilisez /profile d'abord."

            equipped_items = equipment_repository.list_by_player_id(profile.player.id)
            active_class = class_repository.get_current_class_for_player(profile.player.id)

            stats = StatsService().calculate_player_stats(
                profile=profile,
                equipped_items=equipped_items,
                active_class=active_class,
            )

        regenerated_current_hp = self.get_regenerated_player_hp(
            player_id=profile.player.id,
            max_hp=stats.max_hp,
            hp_regeneration=stats.hp_regeneration,
        )

        participant = EncounterParticipant(
            user_id=user_id,
            player_id=profile.player.id,
            display_name=display_name,
            avatar_url=avatar_url,
            current_hp=profile.player.current_hp,
            max_hp=profile.player.max_hp,
            stats=profile.player.stats,
        )

        encounter.participants[user_id] = participant

        return True, "Vous avez rejoint le combat."

    def resolve_active_encounter(self, encounter):
        if encounter is None:
            return None

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            equipment_repository = EquipmentRepository(session)
            class_repository = ClassRepository(session)
            mob_repository = MobRepository(session)

            mob = mob_repository.get_by_code(encounter.mob_state.code)
            if mob is None:
                return None

            party = []

            for participant in encounter.participants.values():
                profile = player_repository.get_by_discord_id(participant.user_id)
                if profile is None:
                    continue

                equipped_items = equipment_repository.list_by_player_id(participant.player_id)
                active_class = class_repository.get_current_class_for_player(participant.player_id)

                stats = StatsService().calculate_player_stats(
                    profile=profile,
                    equipped_items=equipped_items,
                    active_class=active_class,
                )

                party.append(
                    {
                        "player_id": participant.player_id,
                        "user_id": participant.user_id,
                        "name": participant.display_name,
                        "avatar_url": participant.avatar_url,
                        "current_hp": participant.current_hp,
                        "max_hp": participant.max_hp,
                        "stats": stats,
                    }
                )

        if not party:
            return None

        return PartyCombatService().fight_party_vs_mob(
            party=party,
            mob=mob,
        )

    def persist_final_players_hp(self, result) -> None:
        if not result.turn_logs:
            return

        final_turn = result.turn_logs[-1]
        final_players_state = final_turn.players_state

        with get_db_session() as session:
            player_health_repository = PlayerHealthRepository(session)

            for player_state in final_players_state:
                player_id = player_state["player_id"]

                player_health_repository.update_current_hp(
                    player_id=player_id,
                    current_hp=player_state["current_hp"],
                )

    def apply_rewards(self, encounter, result) -> None:
        if encounter is None:
            return

        if not result.victory:
            return

        surviving_names = set(result.surviving_players)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)

            for participant in encounter.participants.values():
                if participant.display_name not in surviving_names:
                    continue

                player_repository.add_gold(participant.player_id, result.gold_gained)
                player_repository.add_xp(participant.player_id, result.xp_gained)
    
    def unregister_participant(
        self,
        encounter,
        user_id: int,
    ) -> tuple[bool, str]:
        if encounter is None:
            return False, "Aucun combat à quitter."

        if user_id not in encounter.participants:
            return False, "Vous n'avez pas rejoint ce combat."

        del encounter.participants[user_id]
        return True, "Vous avez quitté le combat."