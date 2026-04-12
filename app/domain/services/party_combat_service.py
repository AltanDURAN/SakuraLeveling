import random

from app.domain.entities.mob_definition import MobDefinition
from app.domain.value_objects.party_battle_result import PartyBattleResult
from app.domain.value_objects.party_battle_turn_log import PartyBattleTurnLog
from app.domain.value_objects.stats import Stats


class PartyCombatService:
    def fight_party_vs_mob(
        self,
        party: list[tuple[str, Stats]],
        mob: MobDefinition,
    ) -> PartyBattleResult:
        mob_hp = mob.current_hp
        turns = 0
        turn_logs: list[PartyBattleTurnLog] = []

        alive_party = [
            {
                "name": player_name,
                "stats": stats,
                "hp": stats.max_hp,
            }
            for player_name, stats in party
        ]

        while mob_hp > 0 and any(player["hp"] > 0 for player in alive_party):
            turns += 1
            player_actions: list[str] = []

            for player in alive_party:
                if player["hp"] <= 0:
                    continue

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
                player_actions.append(action_text)

                if mob_hp <= 0:
                    break

            if mob_hp <= 0:
                turn_logs.append(
                    PartyBattleTurnLog(
                        turn_number=turns,
                        player_actions=player_actions,
                        mob_action=f"{mob.name} est vaincu.",
                        party_hp_summary=self._build_party_hp_summary(alive_party),
                        mob_hp_after=mob_hp,
                    )
                )
                break

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
                    player_actions=player_actions,
                    mob_action=mob_action,
                    party_hp_summary=self._build_party_hp_summary(alive_party),
                    mob_hp_after=mob_hp,
                )
            )

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
                f"Le groupe a vaincu {mob.name} en {turns} tours."
                if victory
                else f"Le groupe a été vaincu par {mob.name}."
            ),
            turn_logs=turn_logs,
        )

    def _build_party_hp_summary(self, alive_party: list[dict]) -> str:
        return "\n".join(
            f"{player['name']} : {player['hp']} PV"
            for player in alive_party
        )