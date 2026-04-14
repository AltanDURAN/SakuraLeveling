import random

from app.domain.entities.mob_definition import MobDefinition
from app.domain.value_objects.battle_result import BattleResult
from app.domain.value_objects.battle_turn_log import BattleTurnLog
from app.domain.value_objects.stats import Stats


class CombatService:
    def fight_player_vs_mob(
        self,
        player_stats: Stats,
        mob: MobDefinition,
    ) -> BattleResult:
        player_hp = player_stats.max_hp
        mob_hp = mob.current_hp
        turns = 0
        turn_logs: list[BattleTurnLog] = []

        while player_hp > 0 and mob_hp > 0:
            turns += 1

            player_damage = max(1, player_stats.attack - mob.defense)
            player_crit = False

            if random.random() < player_stats.crit_chance:
                player_damage = int(player_damage * player_stats.crit_damage)
                player_crit = True

            mob_hp -= player_damage
            mob_hp = max(0, mob_hp)

            player_dodged = False
            mob_damage = 0

            if mob_hp > 0:
                if random.random() < player_stats.dodge:
                    player_dodged = True
                    mob_damage = 0
                else:
                    mob_damage = max(1, mob.attack - player_stats.defense)
                    player_hp -= mob_damage
                    player_hp = max(0, player_hp)

            turn_logs.append(
                BattleTurnLog(
                    turn_number=turns,
                    player_damage_dealt=player_damage,
                    player_crit=player_crit,
                    mob_damage_dealt=mob_damage,
                    player_dodged=player_dodged,
                    player_hp_after=player_hp,
                    mob_hp_after=mob_hp,
                )
            )

            if mob_hp <= 0:
                return BattleResult(
                    victory=True,
                    turns=turns,
                    player_remaining_hp=player_hp,
                    mob_remaining_hp=mob_hp,
                    xp_gained=mob.xp_reward,
                    gold_gained=mob.gold_reward,
                    items_gained=[],
                    leveled_up=False,
                    new_level=None,
                    summary=f"Vous avez vaincu **{mob.name}** en {turns} tour(s).",
                    turn_logs=turn_logs,
                    mob_name=mob.name,
                    mob_image_name=mob.image_name,
                )

            if player_hp <= 0:
                return BattleResult(
                    victory=False,
                    turns=turns,
                    player_remaining_hp=player_hp,
                    mob_remaining_hp=mob_hp,
                    xp_gained=0,
                    gold_gained=0,
                    items_gained=[],
                    leveled_up=False,
                    new_level=None,
                    summary=f"Vous avez été vaincu par **{mob.name}** en {turns} tour(s).",
                    turn_logs=turn_logs,
                    mob_name=mob.name,
                    mob_image_name=mob.image_name,
                )

        return BattleResult(
            victory=False,
            turns=turns,
            player_remaining_hp=player_hp,
            mob_remaining_hp=mob_hp,
            xp_gained=0,
            gold_gained=0,
            items_gained=[],
            leveled_up=False,
            new_level=None,
            summary="Le combat s'est terminé de manière inattendue.",
            turn_logs=turn_logs,
            mob_name=mob.name,
            mob_image_name=mob.image_name,
        )