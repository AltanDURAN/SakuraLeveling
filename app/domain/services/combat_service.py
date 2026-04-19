import random

from app.domain.entities.mob_definition import MobDefinition
from app.domain.value_objects.battle_result import BattleResult
from app.domain.value_objects.stats import Stats


class CombatService:
    def fight_player_vs_mob(
        self,
        player_stats: Stats,
        mob: MobDefinition,
    ) -> BattleResult:
        player_hp = player_stats.max_hp
        mob_hp = mob.current_hp

        player_gauge = 0
        mob_gauge = 0
        turns = 0
        turn_logs: list[dict] = []

        while player_hp > 0 and mob_hp > 0:
            player_gauge += player_stats.speed
            mob_gauge += mob.speed

            acted = False

            while player_gauge >= 100 and player_hp > 0 and mob_hp > 0:
                turns += 1
                acted = True
                player_gauge -= 100

                if player_stats.hp_regeneration > 0:
                    player_hp = min(player_stats.max_hp, player_hp + player_stats.hp_regeneration)

                player_damage = max(1, player_stats.attack - mob.defense)
                is_crit = False
                mob_dodged = False

                if random.random() < (player_stats.crit_chance / 100):
                    player_damage = int(player_damage * (player_stats.crit_damage / 100))
                    is_crit = True

                mob_hp_before = mob_hp

                if random.random() < (mob.dodge / 100):
                    player_damage = 0
                    mob_dodged = True
                else:
                    mob_hp -= player_damage
                    mob_hp = max(0, mob_hp)

                turn_logs.append(
                    {
                        "turn": turns,
                        "actor": "player",
                        "damage": player_damage,
                        "is_crit": is_crit,
                        "target_dodged": mob_dodged,
                        "player_hp": player_hp,
                        "mob_hp_before": mob_hp_before,
                        "mob_hp_after": mob_hp,
                    }
                )

                if mob_hp <= 0:
                    return BattleResult(
                        victory=True,
                        turns=turns,
                        player_remaining_hp=max(0, player_hp),
                        mob_remaining_hp=max(0, mob_hp),
                        xp_gained=mob.xp_reward,
                        gold_gained=mob.gold_reward,
                        items_gained=[],
                        leveled_up=False,
                        new_level=None,
                        summary=f"Vous avez vaincu **{mob.name}** en {turns} action(s).",
                        turn_logs=turn_logs,
                        mob_name=mob.name,
                        mob_image_name=mob.image_name,
                    )

            while mob_gauge >= 100 and player_hp > 0 and mob_hp > 0:
                turns += 1
                acted = True
                mob_gauge -= 100

                if mob.hp_regeneration > 0:
                    mob_hp = min(mob.max_hp, mob_hp + mob.hp_regeneration)

                player_hp_before = player_hp
                mob_damage = max(1, mob.attack - player_stats.defense)
                mob_is_crit = False
                player_dodged = False

                if random.random() < (mob.crit_chance / 100):
                    mob_damage = int(mob_damage * (mob.crit_damage / 100))
                    mob_is_crit = True

                if random.random() < (player_stats.dodge / 100):
                    mob_damage = 0
                    player_dodged = True
                else:
                    player_hp -= mob_damage
                    player_hp = max(0, player_hp)

                turn_logs.append(
                    {
                        "turn": turns,
                        "actor": "mob",
                        "damage": mob_damage,
                        "is_crit": mob_is_crit,
                        "target_dodged": player_dodged,
                        "player_hp_before": player_hp_before,
                        "player_hp_after": player_hp,
                        "mob_hp": mob_hp,
                    }
                )

                if player_hp <= 0:
                    return BattleResult(
                        victory=False,
                        turns=turns,
                        player_remaining_hp=max(0, player_hp),
                        mob_remaining_hp=max(0, mob_hp),
                        xp_gained=0,
                        gold_gained=0,
                        items_gained=[],
                        leveled_up=False,
                        new_level=None,
                        summary=f"Vous avez été vaincu par **{mob.name}** en {turns} action(s).",
                        turn_logs=turn_logs,
                        mob_name=mob.name,
                        mob_image_name=mob.image_name,
                    )

            if not acted:
                continue

        return BattleResult(
            victory=False,
            turns=turns,
            player_remaining_hp=max(0, player_hp),
            mob_remaining_hp=max(0, mob_hp),
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