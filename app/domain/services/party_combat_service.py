import random

from app.domain.entities.mob_definition import MobDefinition
from app.domain.value_objects.party_battle_result import PartyBattleResult
from app.domain.value_objects.party_battle_turn_log import PartyBattleTurnLog
from app.domain.value_objects.stats import Stats


class PartyCombatService:
    def fight_party_vs_mob(
        self,
        party: list[dict],
        mob: MobDefinition,
    ) -> PartyBattleResult:
        mob_hp = mob.current_hp
        mob_gauge = 0
        turns = 0
        turn_logs: list[PartyBattleTurnLog] = []

        alive_party = [
            {
                "player_id": player["player_id"],
                "user_id": player["user_id"],
                "name": player["name"],
                "avatar_url": player["avatar_url"],
                "stats": player["stats"],
                "hp": player["current_hp"],
                "max_hp": player["max_hp"],
                "gauge": 0,
            }
            for player in party
        ]

        while mob_hp > 0 and any(player["hp"] > 0 for player in alive_party):
            for player in alive_party:
                if player["hp"] > 0:
                    player["gauge"] += player["stats"].speed

            mob_gauge += mob.speed

            acted = False

            for player in alive_party:
                while player["gauge"] >= 100 and player["hp"] > 0 and mob_hp > 0:
                    turns += 1
                    acted = True
                    player["gauge"] -= 100

                    stats: Stats = player["stats"]
                    damage = max(1, stats.attack - mob.defense)
                    crit = False

                    if random.random() < stats.crit_chance:
                        damage = int(damage * stats.crit_damage)
                        crit = True

                    mob_hp -= damage
                    mob_hp = max(0, mob_hp)

                    action_text = f"{player['name']} inflige {damage} dégâts"
                    if crit:
                        action_text += " (CRIT)"

                    turn_logs.append(
                        PartyBattleTurnLog(
                            turn_number=turns,
                            player_actions=[action_text],
                            mob_action=f"{mob.name} subit l'attaque.",
                            players_state=[
                                {
                                    "player_id": member["player_id"],
                                    "user_id": member["user_id"],
                                    "name": member["name"],
                                    "avatar_url": member["avatar_url"],
                                    "current_hp": member["hp"],
                                    "max_hp": member["max_hp"],
                                }
                                for member in alive_party
                            ],
                            mob_state={
                                "name": mob.name,
                                "image_name": mob.image_name,
                                "current_hp": mob_hp,
                                "max_hp": mob.max_hp,
                                "attack": mob.attack,
                                "defense": mob.defense,
                                "speed": mob.speed,
                            },
                        )
                    )

                    if mob_hp <= 0:
                        break

            while mob_gauge >= 100 and mob_hp > 0 and any(player["hp"] > 0 for player in alive_party):
                turns += 1
                acted = True
                mob_gauge -= 100

                possible_targets = [player for player in alive_party if player["hp"] > 0]
                target = random.choice(possible_targets)

                target_stats: Stats = target["stats"]

                if random.random() < target_stats.dodge:
                    mob_action = f"{mob.name} attaque {target['name']}, mais l'attaque est esquivée."
                else:
                    mob_damage = max(1, mob.attack - target_stats.defense)
                    target["hp"] -= mob_damage
                    target["hp"] = max(0, target["hp"])
                    mob_action = f"{mob.name} attaque {target['name']} et inflige {mob_damage} dégâts."

                turn_logs.append(
                    PartyBattleTurnLog(
                        turn_number=turns,
                        player_actions=[],
                        mob_action=mob_action,
                        players_state=[
                            {
                                "player_id": member["player_id"],
                                "user_id": member["user_id"],
                                "name": member["name"],
                                "avatar_url": member["avatar_url"],
                                "current_hp": member["hp"],
                                "max_hp": member["max_hp"],
                            }
                            for member in alive_party
                        ],
                        mob_state={
                            "name": mob.name,
                            "image_name": mob.image_name,
                            "current_hp": mob_hp,
                            "max_hp": mob.max_hp,
                            "attack": mob.attack,
                            "defense": mob.defense,
                            "speed": mob.speed,
                        },
                    )
                )

                if not any(player["hp"] > 0 for player in alive_party):
                    break

            if not acted:
                continue

        surviving_players = [player["name"] for player in alive_party if player["hp"] > 0]
        defeated_players = [player["name"] for player in alive_party if player["hp"] <= 0]
        victory = mob_hp <= 0

        return PartyBattleResult(
            victory=victory,
            turns=turns,
            mob_name=mob.name,
            mob_image_name=mob.image_name,
            mob_remaining_hp=mob_hp,
            surviving_players=surviving_players,
            defeated_players=defeated_players,
            xp_gained=mob.xp_reward if victory else 0,
            gold_gained=mob.gold_reward if victory else 0,
            summary=(
                f"Le groupe a vaincu {mob.name} en {turns} action(s)."
                if victory
                else f"Le groupe a été vaincu par {mob.name}."
            ),
            turn_logs=turn_logs,
        )