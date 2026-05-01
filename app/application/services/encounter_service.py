from datetime import datetime, UTC

from app.bot.runtime.encounter_participant import EncounterParticipant
from app.domain.services.health_regeneration_service import HealthRegenerationService
from app.domain.services.loot_service import LootService
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.services.power_score_service import PowerScoreService
from app.domain.services.reward_distribution_service import RewardDistributionService
from app.domain.services.stats_service import StatsService
from app.domain.value_objects.battle_summary import BattleSummary
from app.domain.value_objects.player_reward import PlayerReward
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_health_repository import PlayerHealthRepository
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
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
            current_hp=regenerated_current_hp,
            max_hp=stats.max_hp,
            stats=stats,
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

    def apply_rewards(self, encounter, result) -> BattleSummary | None:
        if encounter is None:
            return None

        mob_code = encounter.mob_state.code

        power_score_service = PowerScoreService()
        reward_distribution_service = RewardDistributionService()
        loot_service = LootService()

        with get_db_session() as session:
            mob_repository = MobRepository(session)
            mob = mob_repository.get_by_code(mob_code)

        if mob is None:
            return None

        rewards: list[PlayerReward] = []
        contributions_by_id = {c.player_id: c for c in result.contributions}

        if not result.victory:
            for participant in encounter.participants.values():
                contribution = contributions_by_id.get(participant.player_id)
                rewards.append(
                    PlayerReward(
                        player_id=participant.player_id,
                        user_id=participant.user_id,
                        name=participant.display_name,
                        avatar_url=participant.avatar_url,
                        gold=0,
                        xp=0,
                        items=[],
                        contribution=contribution,
                    )
                )

            return BattleSummary(
                outcome="defeat",
                mob_name=mob.name,
                mob_image_name=mob.image_name,
                mob_family=mob.family,
                turns=result.turns,
                rewards=rewards,
                base_xp_reward=mob.xp_reward,
                base_gold_reward=mob.gold_reward,
            )

        mob_power = power_score_service.calculate_from_mob(mob)
        player_powers: dict[int, int] = {}
        for participant in encounter.participants.values():
            player_powers[participant.player_id] = power_score_service.calculate_from_stats(
                participant.stats
            )

        contribution_shares = reward_distribution_service.compute_contribution_shares(
            contributions=result.contributions,
        )
        gold_per_player = reward_distribution_service.distribute_gold(
            mob_gold_reward=mob.gold_reward,
            contributions=result.contributions,
        )
        xp_per_player = reward_distribution_service.distribute_xp(
            mob_xp_reward=mob.xp_reward,
            mob_power=mob_power,
            player_powers=player_powers,
            contributions=result.contributions,
        )

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            kill_repository = PlayerKillRepository(session)
            inventory_repository = InventoryRepository(session)
            item_repository = ItemRepository(session)

            for participant in encounter.participants.values():
                contribution = contributions_by_id.get(participant.player_id)
                survived = contribution is not None and contribution.survived

                if not survived:
                    rewards.append(
                        PlayerReward(
                            player_id=participant.player_id,
                            user_id=participant.user_id,
                            name=participant.display_name,
                            avatar_url=participant.avatar_url,
                            gold=0,
                            xp=0,
                            items=[],
                            contribution=contribution,
                            contribution_share=0.0,
                        )
                    )
                    continue

                gold = gold_per_player.get(participant.player_id, 0)
                xp = xp_per_player.get(participant.player_id, 0)
                dropped_items = loot_service.generate_loot(mob)

                if gold > 0:
                    player_repository.add_gold(participant.player_id, gold)
                if xp > 0:
                    player_repository.add_xp(participant.player_id, xp)

                kill_repository.increment(participant.player_id, mob_code)

                for item_code, quantity in dropped_items:
                    item = item_repository.get_by_code(item_code)
                    if item is None:
                        continue
                    inventory_repository.add_item(
                        player_id=participant.player_id,
                        item_definition_id=item.id,
                        quantity=quantity,
                    )

                rewards.append(
                    PlayerReward(
                        player_id=participant.player_id,
                        user_id=participant.user_id,
                        name=participant.display_name,
                        avatar_url=participant.avatar_url,
                        gold=gold,
                        xp=xp,
                        items=dropped_items,
                        contribution=contribution,
                        contribution_share=contribution_shares.get(
                            participant.player_id, 0.0
                        ),
                    )
                )

        return BattleSummary(
            outcome="victory",
            mob_name=mob.name,
            mob_image_name=mob.image_name,
            mob_family=mob.family,
            turns=result.turns,
            rewards=rewards,
            base_xp_reward=mob.xp_reward,
            base_gold_reward=mob.gold_reward,
        )
    
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