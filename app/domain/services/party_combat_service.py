import random

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.title_bonus_service import TitleBonuses
from app.domain.value_objects.party_battle_result import PartyBattleResult
from app.domain.value_objects.party_battle_turn_log import PartyBattleTurnLog
from app.domain.value_objects.player_contribution import PlayerContribution
from app.domain.value_objects.stats import Stats


class PartyCombatService:
    def fight_party_vs_mob(
        self,
        party: list[dict],
        mob: MobDefinition,
        title_bonuses_by_player: dict[int, TitleBonuses] | None = None,
    ) -> PartyBattleResult:
        title_bonuses_by_player = title_bonuses_by_player or {}
        mob_family = mob.family or ""
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

        contributions: dict[int, PlayerContribution] = {
            member["player_id"]: PlayerContribution(
                player_id=member["player_id"],
                user_id=member["user_id"],
                name=member["name"],
                max_hp=member["max_hp"],
                final_hp=member["hp"],
            )
            for member in alive_party
        }

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

                    # Regen tour-par-tour : ne compte PAS comme "PV soignés" pour
                    # la contribution. hp_healed est réservé aux soins actifs
                    # (futur système de classe Soigneur). Le but est d'éviter
                    # qu'un joueur tanky avec gros hp_regen monopolise la part
                    # heal alors qu'il ne fait que se régénérer passivement.
                    if stats.hp_regeneration > 0 and player["hp"] > 0:
                        player["hp"] = min(player["max_hp"], player["hp"] + stats.hp_regeneration)

                    damage = max(1, stats.attack - mob.defense)
                    crit = False

                    if random.random() < (stats.crit_chance / 100):
                        damage = int(damage * (stats.crit_damage / 100))
                        crit = True

                    # Bonus de titre : +X% dégâts vs famille du mob
                    title_bonus = title_bonuses_by_player.get(player["player_id"])
                    if title_bonus is not None and mob_family:
                        damage = max(
                            1, round(damage * title_bonus.damage_multiplier_vs(mob_family))
                        )

                    mob_hp_before = mob_hp

                    if mob.dodge > 0 and random.random() < (mob.dodge / 100):
                        damage = 0
                        mob_action_text = f"{mob.name} esquive l'attaque de {player['name']}."
                    else:
                        mob_hp -= damage
                        mob_hp = max(0, mob_hp)
                        mob_action_text = f"{mob.name} subit l'attaque."

                    actual_damage = mob_hp_before - mob_hp
                    contributions[player["player_id"]].damage_dealt += actual_damage

                    action_text = f"{player['name']} inflige {damage} dégâts"
                    if crit and damage > 0:
                        action_text += " (CRIT)"

                    turn_logs.append(
                        PartyBattleTurnLog(
                            turn_number=turns,
                            player_actions=[action_text],
                            mob_action=mob_action_text,
                            players_state=[
                                {
                                    "player_id": member["player_id"],
                                    "user_id": member["user_id"],
                                    "name": member["name"],
                                    "avatar_url": member["avatar_url"],
                                    "current_hp": member["hp"],
                                    "max_hp": member["max_hp"],
                                    "attack": member["stats"].attack,
                                    "defense": member["stats"].defense,
                                    "speed": member["stats"].speed,
                                    "crit_chance": member["stats"].crit_chance,
                                    "crit_damage": member["stats"].crit_damage,
                                    "dodge": member["stats"].dodge,
                                    "hp_regeneration": member["stats"].hp_regeneration,
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
                                "crit_chance": mob.crit_chance,
                                "crit_damage": mob.crit_damage,
                                "dodge": mob.dodge,
                                "hp_regeneration": mob.hp_regeneration,
                            },
                        )
                    )

                    if mob_hp <= 0:
                        break

            while mob_gauge >= 100 and mob_hp > 0 and any(player["hp"] > 0 for player in alive_party):
                turns += 1
                acted = True
                mob_gauge -= 100

                if mob.hp_regeneration > 0:
                    mob_hp = min(mob.max_hp, mob_hp + mob.hp_regeneration)

                possible_targets = [player for player in alive_party if player["hp"] > 0]
                target = random.choice(possible_targets)
                target_stats: Stats = target["stats"]

                if random.random() < (target_stats.dodge / 100):
                    contributions[target["player_id"]].dodges += 1
                    mob_action = f"{mob.name} attaque {target['name']}, mais l'attaque est esquivée."
                else:
                    # Calcul en cascade pour pouvoir comptabiliser le "tanked"
                    # (= ce qu'on aurait pris sans défense ni titre).
                    raw_attack = mob.attack
                    mob_crit = False
                    if random.random() < (mob.crit_chance / 100):
                        raw_attack = int(raw_attack * (mob.crit_damage / 100))
                        mob_crit = True

                    after_defense = max(1, raw_attack - target_stats.defense)

                    target_title_bonus = title_bonuses_by_player.get(target["player_id"])
                    if target_title_bonus is not None and mob_family:
                        mob_damage = max(
                            1,
                            round(
                                after_defense
                                * target_title_bonus.damage_received_multiplier_from(
                                    mob_family
                                )
                            ),
                        )
                    else:
                        mob_damage = after_defense

                    target_hp_before = target["hp"]
                    target["hp"] -= mob_damage
                    target["hp"] = max(0, target["hp"])
                    # damage_tanked = le brut entrant (après crit, avant
                    # réductions). Capture la "valeur encaissée" même
                    # quand la défense + titre absorbent une part.
                    contributions[target["player_id"]].damage_tanked += raw_attack

                    mob_action = f"{mob.name} attaque {target['name']} et inflige {mob_damage} dégâts."
                    if mob_crit and mob_damage > 0:
                        mob_action += " (CRIT)"

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
                                "attack": member["stats"].attack,
                                "defense": member["stats"].defense,
                                "speed": member["stats"].speed,
                                "crit_chance": member["stats"].crit_chance,
                                "crit_damage": member["stats"].crit_damage,
                                "dodge": member["stats"].dodge,
                                "hp_regeneration": member["stats"].hp_regeneration,
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
                            "crit_chance": mob.crit_chance,
                            "crit_damage": mob.crit_damage,
                            "dodge": mob.dodge,
                            "hp_regeneration": mob.hp_regeneration,
                        },
                    )
                )

                if not any(player["hp"] > 0 for player in alive_party):
                    break

            if not acted:
                continue

        for member in alive_party:
            contribution = contributions[member["player_id"]]
            contribution.final_hp = member["hp"]
            contribution.survived = member["hp"] > 0

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
            contributions=list(contributions.values()),
        )
