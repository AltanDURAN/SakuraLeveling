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
        mob_abilities: dict | None = None,
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
        # Capacités spéciales du monstre (particularités propres). Vide = aucune.
        mob_abilities = mob_abilities or {}
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
                # Mana : ressource des compétences actives. Absent hors world
                # boss (pas de loadout) → 0, jamais lu dans ce cas. Ne se
                # régénère PAS en combat (régen hors combat uniquement).
                "mana": player.get("current_mana", player.get("mana_max", 0)),
                "mana_max": player.get("mana_max", 0),
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

        # ─── Particularité : frappe d'ouverture prioritaire (assassin) ───
        # Avant tout, même si le mob n'est pas le plus rapide. Toujours critique,
        # cible la plus faible, série de kills (×2, ×3, …) tant qu'elle tue.
        if "opening_assassinate" in mob_abilities and mob_hp > 0:
            streak = 0
            while any(p["hp"] > 0 for p in alive_party):
                streak += 1
                target = min(
                    (p for p in alive_party if p["hp"] > 0),
                    key=lambda p: (p["hp"], p["max_hp"]),
                )
                dmg, crit, dodged = self._resolve_mob_hit(
                    mob, target, contributions, title_bonuses_by_player,
                    incoming_elemental_mult_by_player, mob_family,
                    extra_multiplier=streak, force_crit=True,
                )
                turns += 1
                if dodged:
                    action = f"⚡ {mob.name} fond sur {target['name']} (assassinat) — esquivé !"
                else:
                    mult = f" ×{streak}" if streak > 1 else ""
                    action = f"⚡ {mob.name} assassine {target['name']} : {dmg} dégâts (CRIT{mult})"
                    if target["hp"] <= 0:
                        action += " — 💀 exécuté !"
                turn_logs.append(self._snapshot(turns, [], action, alive_party, mob, mob_hp))
                # La série continue seulement sur un kill effectif.
                if dodged or target["hp"] > 0:
                    break

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
                    # Chaque compétence tire son effet (basique/spéciale) ; l'effet
                    # ne se déclenche QUE si le joueur peut en payer le mana_cost.
                    # Sinon il fizzle (attaque normale ce tour). Le mana ne se
                    # régénère pas en combat → ressource limitée par combat.
                    turn_effects = []
                    for s in loadout:
                        if s is None:
                            continue
                        eff = _skill_svc.roll_effect(s)
                        cost = getattr(eff, "mana_cost", 0)
                        if cost > 0:
                            if player["mana"] < cost:
                                continue  # pas assez de mana → l'effet ne part pas
                            player["mana"] -= cost
                        turn_effects.append(eff)
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

                    # Avantage élémentaire joueur → cible (±30%). Neutre hors boss.
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
                        self._snapshot(turns, [action_text], mob_action_text,
                                       alive_party, mob, mob_hp)
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

                mob_damage, mob_crit, dodged = self._resolve_mob_hit(
                    mob, target, contributions, title_bonuses_by_player,
                    incoming_elemental_mult_by_player, mob_family,
                )
                if dodged:
                    mob_action = f"{mob.name} attaque {target['name']}, mais l'attaque est esquivée."
                else:
                    mob_action = f"{mob.name} attaque {target['name']} et inflige {mob_damage} dégâts."
                    if mob_crit and mob_damage > 0:
                        mob_action += " (CRIT)"

                turn_logs.append(self._snapshot(turns, [], mob_action, alive_party, mob, mob_hp))

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

        # ─── Particularité : explosion à la mort (kamikaze) ───
        # Le mob mort inflige `attack_multiplier` × attaque à CHAQUE joueur
        # vivant (peut critiquer, peut être esquivé). Ceux qui en meurent
        # perdent or/loot/kill (survived=False plus bas).
        cfg = mob_abilities.get("death_explosion")
        if cfg and mob_hp <= 0:
            victims = [p for p in alive_party if p["hp"] > 0]
            if victims:
                mult = int(cfg.get("attack_multiplier", 3))
                parts = []
                for target in victims:
                    dmg, crit, dodged = self._resolve_mob_hit(
                        mob, target, contributions, title_bonuses_by_player,
                        incoming_elemental_mult_by_player, mob_family,
                        extra_multiplier=mult,
                    )
                    if dodged:
                        parts.append(f"{target['name']} esquive")
                    else:
                        tag = " CRIT" if crit else ""
                        dead = " 💀" if target["hp"] <= 0 else ""
                        parts.append(f"{target['name']} −{dmg}{tag}{dead}")
                turns += 1
                action = f"💥 {mob.name} explose à sa mort ! " + " · ".join(parts)
                turn_logs.append(self._snapshot(turns, [], action, alive_party, mob, mob_hp))

        for member in alive_party:
            contribution = contributions[member["player_id"]]
            contribution.final_hp = member["hp"]
            contribution.final_mana = member["mana"]
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

    # ------------------------------------------------------------------ helpers
    def _resolve_mob_hit(
        self, mob, target, contributions, title_bonuses_by_player,
        incoming_mult_by_player, mob_family,
        extra_multiplier: float = 1.0, force_crit: bool = False, can_dodge: bool = True,
    ) -> tuple[int, bool, bool]:
        """Applique un coup du mob sur un joueur (combat soustractif : crit AVANT
        défense, puis bouclier, puis PV). Mutations : hp/shield de la cible +
        contributions (damage_tanked / dodges). Renvoie (dégâts, crit, esquivé).

        `extra_multiplier` : multiplie l'attaque après le crit (×2, ×3 en série
        d'assassinat ; ×N pour l'explosion). `force_crit` force le critique.
        """
        tstats: Stats = target["stats"]

        if can_dodge and tstats.dodge > 0 and random.random() < (tstats.dodge / 100):
            contributions[target["player_id"]].dodges += 1
            return 0, False, True

        raw_attack = mob.attack
        crit = force_crit or (random.random() < (mob.crit_chance / 100))
        if crit:
            raw_attack = int(raw_attack * (mob.crit_damage / 100))
        if extra_multiplier != 1.0:
            raw_attack = int(raw_attack * extra_multiplier)

        after_defense = max(1, raw_attack - tstats.defense)

        tb = title_bonuses_by_player.get(target["player_id"])
        if tb is not None and mob_family:
            mob_damage = max(
                1, round(after_defense * tb.damage_received_multiplier_from(mob_family))
            )
        else:
            mob_damage = after_defense

        incoming_mult = incoming_mult_by_player.get(target["player_id"], 1.0)
        if incoming_mult != 1.0:
            mob_damage = max(1, round(mob_damage * incoming_mult))

        # Bouclier : absorbe en priorité, avant les PV.
        if target["shield"] > 0 and mob_damage > 0:
            absorbed = min(target["shield"], mob_damage)
            target["shield"] -= absorbed
            mob_damage -= absorbed

        target["hp"] = max(0, target["hp"] - mob_damage)
        # damage_tanked = le brut entrant (après crit/multiplicateur, avant
        # réductions) : capture la "valeur encaissée" même si défense/bouclier
        # en absorbent une part.
        contributions[target["player_id"]].damage_tanked += raw_attack
        return mob_damage, crit, False

    def _snapshot(self, turns, player_actions, mob_action, alive_party, mob, mob_hp) -> PartyBattleTurnLog:
        """Construit un PartyBattleTurnLog (état complet équipe + mob) pour un tour."""
        return PartyBattleTurnLog(
            turn_number=turns,
            player_actions=player_actions,
            mob_action=mob_action,
            players_state=[
                {
                    "player_id": member["player_id"],
                    "user_id": member["user_id"],
                    "name": member["name"],
                    "avatar_url": member["avatar_url"],
                    "current_hp": member["hp"],
                    "max_hp": member["max_hp"],
                    "current_mana": member["mana"],
                    "mana_max": member["mana_max"],
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
