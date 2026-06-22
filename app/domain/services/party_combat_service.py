import random

from app.domain.entities.element_skill import (
    SKILL_KIND_DAMAGE,
    SKILL_KIND_HEAL_ALLY,
    SKILL_KIND_SHIELD_SELF,
    SKILL_KIND_SHIELD_TEAM,
)
from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.skill_effect_service import SkillEffectService
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
        elemental_mult_by_player: dict[int, float] | None = None,
        incoming_elemental_mult_by_player: dict[int, float] | None = None,
        skill_loadouts_by_player: dict | None = None,
        damage_immunity_threshold: int = 0,
        boss_heal_per_turn: int = 0,
        boss_reflect_pct: int = 0,
        boss_adds: dict | None = None,
        max_turns: int = 0,
    ) -> PartyBattleResult:
        title_bonuses_by_player = title_bonuses_by_player or {}
        # Multiplicateurs élémentaires (world boss). Absents pour les
        # encounters classiques (mobs neutres) → 1.0 = aucun effet.
        #   elemental_mult_by_player          : dégâts joueur → cible
        #   incoming_elemental_mult_by_player : dégâts cible → joueur
        elemental_mult_by_player = elemental_mult_by_player or {}
        incoming_elemental_mult_by_player = incoming_elemental_mult_by_player or {}
        # Compétences équipées par joueur : dict[player_id -> list[ElementSkill]].
        # Absentes hors world boss → aucun effet. Résolues par tour (basique, ou
        # spéciale à 10% qui la remplace). Effets en % de stats.
        skill_loadouts_by_player = skill_loadouts_by_player or {}
        _skill_svc = SkillEffectService()
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
                "shield": 0,  # bouclier (compétences défensives/support)
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

        # État des modifiers boss dynamiques (neutres hors world boss).
        boss_adds = boss_adds or {}
        adds_attack = int(boss_adds.get("attack", 0))
        adds_interval = int(boss_adds.get("summon_turn_interval", 0))
        adds_max = int(boss_adds.get("max_active", 0))
        active_adds = 0
        round_count = 0

        while mob_hp > 0 and any(player["hp"] > 0 for player in alive_party):
            round_count += 1
            # Cap de sécurité : évite une boucle infinie si l'auto-soin du boss
            # dépasse les DPS de l'équipe (ni mort ni victoire).
            if max_turns and turns >= max_turns:
                break
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

                    # NOTE: hp_regeneration ne s'applique PAS en combat (V2).
                    # La régen est purement passive entre combats (cf.
                    # HealthRegenerationService).

                    # Résolution des compétences équipées pour CE tour : chaque
                    # compétence tire sa basique (ou sa spéciale à 10% qui la
                    # remplace). Effets appliqués après l'attaque de base.
                    loadout = skill_loadouts_by_player.get(player["player_id"]) or []
                    turn_effects = [
                        _skill_svc.roll_effect(s) for s in loadout if s is not None
                    ]
                    offensive_mult = max(
                        [e.value for e in turn_effects if e.kind == SKILL_KIND_DAMAGE],
                        default=1.0,
                    )

                    # Cascade : crit AVANT défense pour conserver la même
                    # logique côté joueur et côté mob (cf. plus bas, mob → joueur).
                    # Un crit applique son multiplicateur au coup brut, puis
                    # la défense est soustraite ensuite — le crit profite
                    # ainsi pleinement même contre une cible blindée.
                    raw_attack = stats.attack
                    crit = False
                    if random.random() < (stats.crit_chance / 100):
                        raw_attack = int(raw_attack * (stats.crit_damage / 100))
                        crit = True

                    # Compétence offensive équipée : multiplie l'attaque de ce
                    # tour (basique 100%, spéciale 150% à 10%). 1.0 si aucune.
                    special_proc = offensive_mult > 1.0
                    if offensive_mult != 1.0:
                        raw_attack = int(raw_attack * offensive_mult)

                    damage = max(1, raw_attack - mob.defense)

                    # Bonus de titre : +X% dégâts vs famille du mob
                    title_bonus = title_bonuses_by_player.get(player["player_id"])
                    if title_bonus is not None and mob_family:
                        damage = max(
                            1, round(damage * title_bonus.damage_multiplier_vs(mob_family))
                        )

                    # Avantage élémentaire joueur → cible (±50%). Neutre hors boss.
                    elem_mult = elemental_mult_by_player.get(player["player_id"], 1.0)
                    if elem_mult != 1.0:
                        damage = max(1, round(damage * elem_mult))

                    # Seuil d'immunité du boss (par coup) : un coup trop faible
                    # glisse sur la carapace (0 dégât). Neutre hors boss.
                    immune = False
                    if damage_immunity_threshold > 0 and damage < damage_immunity_threshold:
                        damage = 0
                        immune = True

                    mob_hp_before = mob_hp

                    if mob.dodge > 0 and random.random() < (mob.dodge / 100):
                        damage = 0
                        mob_action_text = f"{mob.name} esquive l'attaque de {player['name']}."
                    elif immune:
                        mob_action_text = f"{mob.name} ignore le coup (trop faible)."
                    else:
                        mob_hp -= damage
                        mob_hp = max(0, mob_hp)
                        mob_action_text = f"{mob.name} subit l'attaque."

                    actual_damage = mob_hp_before - mob_hp
                    contributions[player["player_id"]].damage_dealt += actual_damage

                    action_text = f"{player['name']} inflige {damage} dégâts"
                    if crit and damage > 0:
                        action_text += " (CRIT)"
                    if special_proc and damage > 0:
                        action_text += " ✨SPÉCIAL"
                    if immune:
                        action_text = f"{player['name']} : coup ignoré (immunité)"

                    # Reflet de dégâts du boss : renvoie une part au frappeur.
                    if boss_reflect_pct > 0 and actual_damage > 0:
                        reflected = max(1, round(actual_damage * boss_reflect_pct / 100))
                        player["hp"] = max(0, player["hp"] - reflected)
                        action_text += f" (renvoi {reflected})"

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

                    # Effets défensifs / support des compétences (résolus plus
                    # haut dans turn_effects). hp_healed (contribution) = soins +
                    # boucliers donnés aux ALLIÉS uniquement (pas sur soi).
                    for eff in turn_effects:
                        if eff.kind == SKILL_KIND_SHIELD_SELF:
                            player["shield"] += int(stats.defense * eff.value)
                        elif eff.kind == SKILL_KIND_HEAL_ALLY:
                            heal_amt = int(stats.attack * eff.value)
                            # Soigne l'allié vivant au PV le plus bas (hors soi).
                            allies = [
                                m for m in alive_party
                                if m["player_id"] != player["player_id"] and m["hp"] > 0
                            ]
                            if heal_amt > 0 and allies:
                                target_ally = min(allies, key=lambda m: m["hp"])
                                before_hp = target_ally["hp"]
                                target_ally["hp"] = min(
                                    target_ally["max_hp"], target_ally["hp"] + heal_amt
                                )
                                contributions[player["player_id"]].hp_healed += (
                                    target_ally["hp"] - before_hp
                                )
                        elif eff.kind == SKILL_KIND_SHIELD_TEAM:
                            shield_amt = int(stats.defense * eff.value)
                            if shield_amt > 0:
                                for m in alive_party:
                                    if m["hp"] <= 0:
                                        continue
                                    m["shield"] += shield_amt
                                    # Crédit de "soin" = boucliers donnés aux alliés.
                                    if m["player_id"] != player["player_id"]:
                                        contributions[player["player_id"]].hp_healed += shield_amt

                    if mob_hp <= 0:
                        break

            while mob_gauge >= 100 and mob_hp > 0 and any(player["hp"] > 0 for player in alive_party):
                turns += 1
                acted = True
                mob_gauge -= 100

                # NOTE: hp_regeneration des mobs ne s'applique PAS en combat (V2).

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

                    # Avantage élémentaire cible → joueur (±50%). Neutre hors boss.
                    incoming_mult = incoming_elemental_mult_by_player.get(
                        target["player_id"], 1.0
                    )
                    if incoming_mult != 1.0:
                        mob_damage = max(1, round(mob_damage * incoming_mult))

                    # Bouclier (compétences défensives/support) : absorbe en
                    # priorité, avant les PV. damage_tanked (plus bas) reste le
                    # brut entrant → un tank touché peu garde son crédit de tank.
                    if target["shield"] > 0 and mob_damage > 0:
                        absorbed = min(target["shield"], mob_damage)
                        target["shield"] -= absorbed
                        mob_damage -= absorbed

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

            # Invocations (adds) : apparaissent périodiquement puis frappent
            # l'équipe tant que le boss est en vie. Neutre hors world boss.
            if mob_hp > 0 and adds_attack > 0 and adds_interval > 0 and adds_max > 0:
                if round_count % adds_interval == 0 and active_adds < adds_max:
                    active_adds += 1
                for _ in range(active_adds):
                    alive = [p for p in alive_party if p["hp"] > 0]
                    if not alive:
                        break
                    victim = random.choice(alive)
                    add_dmg = max(1, adds_attack - victim["stats"].defense)
                    victim["hp"] = max(0, victim["hp"] - add_dmg)
                    contributions[victim["player_id"]].damage_tanked += adds_attack

            # Auto-soin du boss : régénère des PV chaque round (capé au max).
            # Neutre hors world boss. Le cap de tours évite la boucle infinie.
            if boss_heal_per_turn > 0 and mob_hp > 0:
                mob_hp = min(mob.max_hp, mob_hp + boss_heal_per_turn)

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
