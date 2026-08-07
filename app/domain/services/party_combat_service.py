import random

from app.domain.entities.element_skill import (
    SKILL_KIND_DAMAGE,
    SKILL_KIND_HEAL_ALLY,
    SKILL_KIND_SHIELD_SELF,
    SKILL_KIND_SHIELD_TEAM,
)
from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.power_score_service import PowerScoreService
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
        elemental_mult_by_player = elemental_mult_by_player or {}
        incoming_elemental_mult_by_player = incoming_elemental_mult_by_player or {}
        skill_loadouts_by_player = skill_loadouts_by_player or {}
        ab = mob_abilities or {}
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
                "mana": player.get("current_mana", player.get("mana_max", 0)),
                "mana_max": player.get("mana_max", 0),
                "gauge": 0,
                "shield": 0,       # bouclier (compétences défensives/support)
                "stunned": False,  # étourdi (gobelin géant / banshee)
                "slow": 0,         # stacks de ralentissement (momie)
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

        # ── État du charme (succube) ──
        charmed_id: int | None = None
        _power = PowerScoreService()

        def _charmed_member():
            return next((p for p in alive_party if p["player_id"] == charmed_id), None)

        def _charmed_alive() -> bool:
            m = _charmed_member()
            return m is not None and m["hp"] > 0

        def _party_alive() -> bool:
            return any(p["hp"] > 0 and p["player_id"] != charmed_id for p in alive_party)

        def _mob_targets() -> list:
            return [p for p in alive_party if p["hp"] > 0 and p["player_id"] != charmed_id]

        # ── État des capacités du monstre ──
        mob_shield = mob.max_hp if "shield" in ab else 0
        mob_revived = False
        chaman_pending = False
        chaman_done = False
        liche_single_next = False               # commence par une frappe de zone
        fantome_first_dodged: set[int] = set()

        def _enrage_pct() -> int:
            tiers = ab.get("enrage", {}).get("tiers", [])
            if not tiers or not mob.max_hp:
                return 0
            ratio = mob_hp / mob.max_hp * 100
            return max((b for t, b in tiers if ratio <= t), default=0)

        def _mob_attack_now() -> int:
            a = float(mob.attack)
            if mob_revived:
                a *= 1 + ab.get("revive", {}).get("atk_pct", 0) / 100
            a *= 1 + _enrage_pct() / 100
            return max(1, int(round(a)))

        def _mob_defense_now() -> int:
            d = float(mob.defense)
            if mob_revived:
                d *= 1 + ab.get("revive", {}).get("def_pct", 0) / 100
            d *= 1 + _enrage_pct() / 100
            return int(round(d))

        def snap(action, players=None):
            return self._snapshot(turns, players or [], action, alive_party, mob, mob_hp, mob_shield)

        # ── État des modifiers boss dynamiques (neutres hors world boss) ──
        boss_adds = boss_adds or {}
        adds_attack = int(boss_adds.get("attack", 0))
        adds_interval = int(boss_adds.get("summon_turn_interval", 0))
        adds_max = int(boss_adds.get("max_active", 0))
        active_adds = 0
        round_count = 0

        # ─── Frappe d'ouverture prioritaire (assassin) ───
        if "opening_assassinate" in ab and mob_hp > 0:
            streak = 0
            while any(p["hp"] > 0 for p in alive_party):
                streak += 1
                target = min((p for p in alive_party if p["hp"] > 0),
                             key=lambda p: (p["hp"], p["max_hp"]))
                dmg, crit, dodged = self._resolve_mob_hit(
                    mob, target, contributions, title_bonuses_by_player,
                    incoming_elemental_mult_by_player, mob_family,
                    extra_multiplier=streak, force_crit=True)
                turns += 1
                if dodged:
                    action = f"⚡ {mob.name} fond sur {target['name']} (assassinat) — esquivé !"
                else:
                    mult = f" ×{streak}" if streak > 1 else ""
                    action = f"⚡ {mob.name} assassine {target['name']} : {dmg} dégâts (CRIT{mult})"
                    if target["hp"] <= 0:
                        action += " — 💀 exécuté !"
                turn_logs.append(snap(action))
                if dodged or target["hp"] > 0:
                    break

        # ─── Charme (succube) ───
        if "charm" in ab and mob_hp > 0:
            living = [p for p in alive_party if p["hp"] > 0]
            if living:
                charmed = max(living, key=lambda p: _power.calculate_from_stats(p["stats"]))
                charmed_id = charmed["player_id"]
                if not _party_alive():
                    charmed["hp"] = 0
                    action = (f"💋 {mob.name} charme {charmed['name']}… "
                              f"seul et envoûté, il est dévoré ! Défaite.")
                else:
                    action = (f"💋 {mob.name} charme {charmed['name']} (le plus puissant) ! "
                              f"Retourné contre les siens — abattez-le pour atteindre {mob.name}.")
                turns += 1
                turn_logs.append(snap(action))

        while mob_hp > 0 and _party_alive():
            round_count += 1
            if max_turns and turns >= max_turns:
                break
            for player in alive_party:
                if player["hp"] > 0:
                    fill = player["stats"].speed
                    if player["slow"] > 0:
                        fill = max(1, fill // 2)   # ralenti (momie) : jauge à 50%
                    player["gauge"] += fill

            mob_gauge += mob.speed
            acted = False

            for player in alive_party:
                while player["gauge"] >= 100 and player["hp"] > 0 and mob_hp > 0:
                    # Étourdi : le tour est consommé pour dissiper le statut, sans action.
                    if player["stunned"]:
                        player["stunned"] = False
                        player["gauge"] -= 100
                        if player["slow"] > 0:
                            player["slow"] -= 1
                        turns += 1
                        acted = True
                        turn_logs.append(snap(f"💫 {player['name']} est étourdi et perd son tour."))
                        continue

                    # Charme : le joueur charmé frappe un allié non-charmé.
                    if player["player_id"] == charmed_id:
                        prey = [p for p in alive_party
                                if p["player_id"] != charmed_id and p["hp"] > 0]
                        if not prey:
                            break
                        turns += 1
                        acted = True
                        player["gauge"] -= 100
                        if player["slow"] > 0:
                            player["slow"] -= 1
                        victim = random.choice(prey)
                        dmg, crit, dodged = self._pvp_hit(player, victim, contributions)
                        act = (f"😈 {player['name']} (charmé) attaque {victim['name']} — esquive !"
                               if dodged else
                               f"😈 {player['name']} (charmé) frappe {victim['name']} : {dmg} dégâts"
                               + (" CRIT" if crit else "")
                               + (" 💀" if victim["hp"] <= 0 else ""))
                        turn_logs.append(snap(act))
                        continue

                    turns += 1
                    acted = True
                    player["gauge"] -= 100
                    if player["slow"] > 0:
                        player["slow"] -= 1

                    # Charme : les non-charmés doivent d'abord abattre le charmé.
                    if _charmed_alive():
                        victim = _charmed_member()
                        dmg, crit, dodged = self._pvp_hit(player, victim, contributions)
                        freed = victim["hp"] <= 0 and not dodged
                        act = (f"{player['name']} vise {victim['name']} (charmé) — esquive !"
                               if dodged else
                               f"{player['name']} frappe {victim['name']} (charmé) : {dmg} dégâts"
                               + (" CRIT" if crit else "")
                               + (f" — 💔 {victim['name']} est libéré !" if freed else ""))
                        turn_logs.append(snap(act))
                        continue

                    stats: Stats = player["stats"]

                    # Compétences équipées (mana-gated) — world boss uniquement.
                    loadout = skill_loadouts_by_player.get(player["player_id"]) or []
                    turn_effects = []
                    for s in loadout:
                        if s is None:
                            continue
                        eff = _skill_svc.roll_effect(s)
                        cost = getattr(eff, "mana_cost", 0)
                        if cost > 0:
                            if player["mana"] < cost:
                                continue
                            player["mana"] -= cost
                        turn_effects.append(eff)
                    offensive_mult = max(
                        [e.value for e in turn_effects if e.kind == SKILL_KIND_DAMAGE],
                        default=1.0,
                    )

                    raw_attack = stats.attack
                    crit = False
                    if random.random() < (stats.crit_chance / 100):
                        raw_attack = int(raw_attack * (stats.crit_damage / 100))
                        crit = True

                    special_proc = offensive_mult > 1.0
                    if offensive_mult != 1.0:
                        raw_attack = int(raw_attack * offensive_mult)

                    damage = max(1, raw_attack - _mob_defense_now())

                    title_bonus = title_bonuses_by_player.get(player["player_id"])
                    if title_bonus is not None and mob_family:
                        damage = max(1, round(damage * title_bonus.damage_multiplier_vs(mob_family)))

                    elem_mult = elemental_mult_by_player.get(player["player_id"], 1.0)
                    if elem_mult != 1.0:
                        damage = max(1, round(damage * elem_mult))

                    immune = False
                    if damage_immunity_threshold > 0 and damage < damage_immunity_threshold:
                        damage = 0
                        immune = True

                    mob_hp_before = mob_hp
                    landed = False

                    fantome_dodge = ("first_hit_dodge" in ab
                                     and player["player_id"] not in fantome_first_dodged)
                    if fantome_dodge:
                        fantome_first_dodged.add(player["player_id"])
                        damage = 0
                        mob_action_text = (f"👻 {mob.name} se dissipe — la première attaque de "
                                           f"{player['name']} est esquivée !")
                    elif mob.dodge > 0 and random.random() < (mob.dodge / 100):
                        damage = 0
                        mob_action_text = f"{mob.name} esquive l'attaque de {player['name']}."
                    elif immune:
                        mob_action_text = f"{mob.name} ignore le coup (trop faible)."
                    else:
                        landed = True
                        # Bouclier du mob (gobelin supérieur) : absorbe avant les PV.
                        to_shield = min(mob_shield, damage) if mob_shield > 0 else 0
                        mob_shield -= to_shield
                        mob_hp = max(0, mob_hp - (damage - to_shield))
                        mob_action_text = f"{mob.name} subit l'attaque."

                    actual_damage = damage if landed else 0
                    contributions[player["player_id"]].damage_dealt += actual_damage

                    action_text = f"{player['name']} inflige {damage} dégâts"
                    if crit and damage > 0:
                        action_text += " (CRIT)"
                    if special_proc and damage > 0:
                        action_text += " ✨SPÉCIAL"
                    if immune:
                        action_text = f"{player['name']} : coup ignoré (immunité)"
                    elif landed and mob_shield > 0:
                        action_text += " 🛡️"

                    if boss_reflect_pct > 0 and actual_damage > 0:
                        reflected = max(1, round(actual_damage * boss_reflect_pct / 100))
                        player["hp"] = max(0, player["hp"] - reflected)
                        action_text += f" (renvoi {reflected})"

                    turn_logs.append(snap(mob_action_text, players=[action_text]))

                    for eff in turn_effects:
                        if eff.kind == SKILL_KIND_SHIELD_SELF:
                            player["shield"] += int(stats.defense * eff.value)
                        elif eff.kind == SKILL_KIND_HEAL_ALLY:
                            heal_amt = int(stats.attack * eff.value)
                            allies = [m for m in alive_party
                                      if m["player_id"] != player["player_id"] and m["hp"] > 0]
                            if heal_amt > 0 and allies:
                                target_ally = min(allies, key=lambda m: m["hp"])
                                before_hp = target_ally["hp"]
                                target_ally["hp"] = min(target_ally["max_hp"], target_ally["hp"] + heal_amt)
                                contributions[player["player_id"]].hp_healed += target_ally["hp"] - before_hp
                        elif eff.kind == SKILL_KIND_SHIELD_TEAM:
                            shield_amt = int(stats.defense * eff.value)
                            if shield_amt > 0:
                                for m in alive_party:
                                    if m["hp"] <= 0:
                                        continue
                                    m["shield"] += shield_amt
                                    if m["player_id"] != player["player_id"]:
                                        contributions[player["player_id"]].hp_healed += shield_amt

                    # Chaman : 1ʳᵉ fois sous 50% PV → soin d'urgence au prochain tour.
                    if (landed and "heal_once_below" in ab and not chaman_done and mob_hp > 0
                            and mob_hp <= mob.max_hp * ab["heal_once_below"].get("hp_pct", 50) / 100):
                        chaman_pending = True
                        chaman_done = True

                    # Résurrection (ange déchu) : 1ʳᵉ mort → revient à 100% PV, +100% atk/déf.
                    if mob_hp <= 0 and "revive" in ab and not mob_revived:
                        mob_revived = True
                        mob_hp = mob.max_hp
                        turn_logs.append(snap(
                            f"👼 {mob.name} renaît à 100% PV, transcendé "
                            f"(+100% attaque et défense) !"))

                    if mob_hp <= 0:
                        break

            # ── Tour du mob ──
            if _charmed_alive():
                mob_gauge = 0  # succube protégée, passive tant que le charmé vit
            while mob_gauge >= 100 and mob_hp > 0 and _party_alive() and not _charmed_alive():
                turns += 1
                acted = True
                mob_gauge -= 100

                # Chaman : soin d'urgence (remplace l'attaque de ce tour).
                if chaman_pending:
                    chaman_pending = False
                    mob_hp = mob.max_hp
                    turn_logs.append(snap(f"✨ {mob.name} canalise et se soigne à 100% PV !"))
                    continue

                # Motif d'attaque : zone / mono ; multi-coups ; alternance (liche).
                aoe = "aoe" in ab
                single_mult = 1.0
                if "alternating" in ab:
                    if liche_single_next:
                        aoe = False
                        single_mult = ab["alternating"].get("single_multiplier", 3)
                    else:
                        aoe = True
                    liche_single_next = not liche_single_next
                hits = int(ab.get("multi_hit", {}).get("hits", 1))
                atk_now = _mob_attack_now()

                for _ in range(hits):
                    pool = _mob_targets()
                    if not pool:
                        break
                    targets = pool if aoe else [random.choice(pool)]
                    parts = []
                    for target in targets:
                        dmg, mob_crit, dodged = self._resolve_mob_hit(
                            mob, target, contributions, title_bonuses_by_player,
                            incoming_elemental_mult_by_player, mob_family,
                            extra_multiplier=single_mult, attack_override=atk_now)
                        # Vol de vie (gargouille)
                        if not dodged and dmg > 0 and "lifesteal" in ab:
                            heal = round(dmg * ab["lifesteal"].get("pct", 0) / 100)
                            if heal > 0:
                                mob_hp = min(mob.max_hp, mob_hp + heal)
                        # Étourdissement (gobelin géant / banshee) — non cumulable
                        stunned_now = False
                        if not dodged and "stun" in ab and not target["stunned"]:
                            if random.random() < ab["stun"].get("chance", 0) / 100:
                                target["stunned"] = True
                                stunned_now = True
                        # Ralentissement (momie, mono-cible) — +1 stack de durée
                        if not dodged and not aoe and "slow" in ab:
                            target["slow"] += 1
                        # Kill → recharge du bouclier (gobelin supérieur)
                        if target["hp"] <= 0 and ab.get("shield", {}).get("reset_on_kill"):
                            mob_shield = mob.max_hp
                        if dodged:
                            parts.append(f"{target['name']} esquive")
                        else:
                            tag = " CRIT" if mob_crit else ""
                            tag += " 💫" if stunned_now else ""
                            tag += " 🐌" if (not aoe and "slow" in ab) else ""
                            tag += " 💀" if target["hp"] <= 0 else ""
                            parts.append(f"{target['name']} −{dmg}{tag}")
                    verb = "déchaîne une frappe de zone" if aoe else "frappe"
                    heal_tag = " 🩸" if "lifesteal" in ab else ""
                    turn_logs.append(snap(f"{mob.name} {verb}{heal_tag} : " + " · ".join(parts)))
                    if not _party_alive():
                        break

                if not _party_alive():
                    break

            # Invocations (adds) — world boss.
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

            # Auto-soin du boss — world boss.
            if boss_heal_per_turn > 0 and mob_hp > 0:
                mob_hp = min(mob.max_hp, mob_hp + boss_heal_per_turn)

            if not acted:
                continue

        # ─── Explosion à la mort (kamikaze) ───
        cfg = ab.get("death_explosion")
        if cfg and mob_hp <= 0:
            victims = [p for p in alive_party if p["hp"] > 0]
            if victims:
                mult = int(cfg.get("attack_multiplier", 3))
                parts = []
                for target in victims:
                    dmg, crit, dodged = self._resolve_mob_hit(
                        mob, target, contributions, title_bonuses_by_player,
                        incoming_elemental_mult_by_player, mob_family,
                        extra_multiplier=mult)
                    if dodged:
                        parts.append(f"{target['name']} esquive")
                    else:
                        tag = " CRIT" if crit else ""
                        dead = " 💀" if target["hp"] <= 0 else ""
                        parts.append(f"{target['name']} −{dmg}{tag}{dead}")
                turns += 1
                turn_logs.append(snap(f"💥 {mob.name} explose à sa mort ! " + " · ".join(parts)))

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
        attack_override: int | None = None,
    ) -> tuple[int, bool, bool]:
        """Coup du mob sur un joueur (soustractif : crit AVANT défense, puis
        bouclier, puis PV). `attack_override` = attaque effective (furie/résurrection).
        Renvoie (dégâts, crit, esquivé)."""
        tstats: Stats = target["stats"]

        if can_dodge and tstats.dodge > 0 and random.random() < (tstats.dodge / 100):
            contributions[target["player_id"]].dodges += 1
            return 0, False, True

        raw_attack = mob.attack if attack_override is None else attack_override
        crit = force_crit or (random.random() < (mob.crit_chance / 100))
        if crit:
            raw_attack = int(raw_attack * (mob.crit_damage / 100))
        if extra_multiplier != 1.0:
            raw_attack = int(raw_attack * extra_multiplier)

        after_defense = max(1, raw_attack - tstats.defense)

        tb = title_bonuses_by_player.get(target["player_id"])
        if tb is not None and mob_family:
            mob_damage = max(1, round(after_defense * tb.damage_received_multiplier_from(mob_family)))
        else:
            mob_damage = after_defense

        incoming_mult = incoming_mult_by_player.get(target["player_id"], 1.0)
        if incoming_mult != 1.0:
            mob_damage = max(1, round(mob_damage * incoming_mult))

        if target["shield"] > 0 and mob_damage > 0:
            absorbed = min(target["shield"], mob_damage)
            target["shield"] -= absorbed
            mob_damage -= absorbed

        target["hp"] = max(0, target["hp"] - mob_damage)
        contributions[target["player_id"]].damage_tanked += raw_attack
        return mob_damage, crit, False

    def _pvp_hit(self, attacker, target, contributions) -> tuple[int, bool, bool]:
        """Coup joueur → joueur (charme) : crit AVANT défense, puis bouclier, puis PV."""
        astats: Stats = attacker["stats"]
        tstats: Stats = target["stats"]

        if tstats.dodge > 0 and random.random() < (tstats.dodge / 100):
            contributions[target["player_id"]].dodges += 1
            return 0, False, True

        raw = astats.attack
        crit = random.random() < (astats.crit_chance / 100)
        if crit:
            raw = int(raw * (astats.crit_damage / 100))
        dmg = max(1, raw - tstats.defense)
        if target["shield"] > 0 and dmg > 0:
            absorbed = min(target["shield"], dmg)
            target["shield"] -= absorbed
            dmg -= absorbed
        target["hp"] = max(0, target["hp"] - dmg)
        contributions[target["player_id"]].damage_tanked += raw
        return dmg, crit, False

    def _snapshot(self, turns, player_actions, mob_action, alive_party, mob, mob_hp,
                  mob_shield: int = 0) -> PartyBattleTurnLog:
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
                    "stunned": member.get("stunned", False),
                    "slow": member.get("slow", 0),
                }
                for member in alive_party
            ],
            mob_state={
                "name": mob.name,
                "image_name": mob.image_name,
                "current_hp": mob_hp,
                "max_hp": mob.max_hp,
                "shield": mob_shield,
                "attack": mob.attack,
                "defense": mob.defense,
                "speed": mob.speed,
                "crit_chance": mob.crit_chance,
                "crit_damage": mob.crit_damage,
                "dodge": mob.dodge,
                "hp_regeneration": mob.hp_regeneration,
            },
        )
