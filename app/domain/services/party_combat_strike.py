"""Les COUPS : la frappe d'un joueur (`_strike`), celle d'un monstre
(`_resolve_mob_hit`) et ses effets dessinés, le coup d'un allié charmé.

Méthodes de `PartyCombatService` (mixin), sorties de
`party_combat_service.py` le 28/11/2026 (audit) : texte inchangé. L'état
du combat en cours vit sur l'instance (une par combat)."""

import random

from app.domain.services.damage_formula import resolve_hit, thorns_recoil
from app.domain.value_objects.stats import Stats


from app.domain.services.party_combat_rules import ROOT_VENOM_ATK_CAP_PCT, ROOT_VENOM_PCT


class StrikeMixin:
    def _mob_hit_fx(self, target, E, dmg: int, crit: bool, dodged: bool, style: str,
                    shield_before: int) -> None:
        """Événement d'un coup d'ennemi sur un joueur (esquive, coup, part
        absorbée par le bouclier ou annulée)."""
        src = self.ek(E)
        if dodged:
            self._emit("dodge", self.pk(target), source=src)
            return
        absorbed = max(0, shield_before - target["shield"])
        if target.get("_ward"):
            self._emit("block", self.pk(target), source=src)
        elif dmg > 0 or absorbed == 0:
            self._emit("crit" if crit else "hit", self.pk(target), dmg, source=src, style=style)
        if absorbed > 0:
            self._emit("block", self.pk(target), absorbed, source=src)

    def _strike(self, player, E, offensive_mult: float = 1.0, prefix: str = "",
                chained: bool = False, style: str = "slash") -> int:
        """UNE attaque d'un joueur sur l'ennemi E (toute la chaîne de
        dégâts) + ses effets immédiats. Réutilisée par Coup double,
        Riposte, Piqué et Œil de la tempête ; `chained` = coup issu d'un
        autre effet, qui ne déclenche ni zone ni réaction en chaîne.
        Renvoie les dégâts portés aux PV."""
        stats: Stats = player["stats"]
        mine = self.P(player)
        mob = E["mob"]
        raw_attack = stats.attack
        if mine.has("rising_fury") and player["fury"]:
            raw_attack = int(raw_attack * (1 + min(20, player["fury"]) / 100))
        if mine.has("lunar_rage") and player["hp"] < player["max_hp"] * 0.5:
            raw_attack = round(raw_attack * 1.15)   # Rage lunaire
        crit = False
        if random.random() < (stats.crit_chance / 100):
            raw_attack = int(raw_attack * (stats.crit_damage / 100))
            crit = True
        # Frappe d'ouverture : 1re attaque forcément critique ; si elle
        # l'était déjà, super-critique (les deux critiques se cumulent).
        if mine.has("first_strike_crit") and not player["opened"]:
            raw_attack = int(raw_attack * (stats.crit_damage / 100))
            crit = True
        player["opened"] = True
        # Valse sanglante : le coup qui suit une esquive est critique et
        # fait saigner.
        waltz = mine.has("bloody_waltz") and player["waltz"]
        if waltz:
            player["waltz"] = False
            if not crit:
                raw_attack = int(raw_attack * (stats.crit_damage / 100))
                crit = True

        special_proc = offensive_mult > 1.0
        if offensive_mult != 1.0:
            raw_attack = int(raw_attack * offensive_mult)

        mob_def = self._mob_defense_now(E)
        if mine.armor_penetration_pct > 0:  # Léthal
            mob_def = int(mob_def * (1 - min(100.0, mine.armor_penetration_pct) / 100))
        if mine.has("devouring_void"):     # Néant dévorant : un coup sur deux
            player["void_hits"] += 1
            if player["void_hits"] % 2 == 0:
                mob_def = int(mob_def * 0.5)
        damage, recoil = resolve_hit(raw_attack, mob_def)

        title_bonus = self.title_bonuses_by_player.get(player["player_id"])
        if title_bonus is not None:     # titres (famille) et cartes (ce monstre)
            title_mult = title_bonus.damage_multiplier_vs(E["family"], E["base"].code)
            if title_mult != 1.0:
                damage = max(1, round(damage * title_mult))

        elem_mult = E["out"].get(player["player_id"], 1.0)
        if elem_mult != 1.0:
            damage = max(1, round(damage * elem_mult))

        aura = self._aura_pct()
        if aura:  # Soigneur dans l'équipe
            damage = max(1, round(damage * (1 + aura / 100)))
        if mine.damage_dealt_pct:  # Titan
            damage = max(1, round(damage * (1 + mine.damage_dealt_pct / 100)))
        if mine.has("elemental_power") and elem_mult > 1.0:
            damage = max(1, round(damage * 1.10))
        if mine.has("executioner") and E["hp"] < E["max_hp"] * 0.5:
            damage = max(1, round(damage * 1.20))
        if mine.has("boss_slayer") and E["is_boss"]:
            damage = max(1, round(damage * 1.15))
        if mine.has("pack_instinct"):   # Instinct de meute : +3 % par allié debout (max 3)
            allies = min(3, self._living_allies(player))
            if allies:
                damage = max(1, round(damage * (1 + 0.03 * allies)))
        if mine.has("ambush") and not E["acted"]:   # Embuscade
            damage = max(1, round(damage * 1.25))
        if player["shadow"]:  # Pas de l'ombre : prochaine action +10 %
            damage = max(1, round(damage * 1.10))
            player["shadow"] = False

        damage = self._guarded(E, damage)     # boss protégé par ses gardes
        immune = False
        if E["immunity"] > 0 and damage < E["immunity"]:
            damage = 0
            immune = True

        landed = False
        void_gaze = mine.has("void_gaze")   # Regard du vide : ni esquive ni fantôme
        fantome_dodge = ("first_hit_dodge" in E["ab"] and not void_gaze
                         and player["player_id"] not in E["ghost_dodged"])
        if fantome_dodge:
            E["ghost_dodged"].add(player["player_id"])
            self._emit("dodge", self.ek(E), source=self.pk(player))
            damage = 0
            mob_action_text = (f"👻 {mob.name} se dissipe — la première attaque de "
                               f"{player['name']} est esquivée !")
        elif mob.dodge > 0 and not void_gaze and random.random() < (mob.dodge / 100):
            damage = 0
            self._emit("dodge", self.ek(E), source=self.pk(player))
            mob_action_text = f"{mob.name} esquive l'attaque de {player['name']}."
        elif immune:
            self._emit("immune", self.ek(E), source=self.pk(player))
            mob_action_text = f"{mob.name} ignore le coup (trop faible)."
        else:
            landed = True
            # Bouclier du mob (gobelin supérieur) : absorbe avant les PV.
            to_shield = min(E["shield"], damage) if E["shield"] > 0 else 0
            E["shield"] -= to_shield
            E["hp"] = max(0, E["hp"] - (damage - to_shield))
            self._emit("crit" if crit else "hit", self.ek(E), damage, source=self.pk(player), style=style,
                       element=E["infusion"].get(player["player_id"], ""), shield=to_shield)
            mob_action_text = f"{mob.name} subit l'attaque."

        actual_damage = damage if landed else 0
        self.contributions[player["player_id"]].damage_dealt += actual_damage
        if landed and mine.has("rising_fury"):
            player["fury"] += 1

        action_text = f"{prefix}{player['name']} inflige {damage} dégâts"
        if len(self.foes) > 1:
            action_text += f" à {mob.name}"
        if crit and damage > 0:
            action_text += " (CRIT)"
        if special_proc and damage > 0:
            action_text += " ✨SPÉCIAL"
        if immune:
            action_text = f"{player['name']} : coup ignoré (immunité)"
        elif landed and E["shield"] > 0:
            action_text += " 🛡️"

        if mine.ally_heal_on_hit_pct > 0 and actual_damage > 0:  # Clerc
            hurt = [m for m in self.alive_party
                    if m is not player and 0 < m["hp"] < m["max_hp"] and not m["absorbed"]
                    and m["player_id"] != self.charmed_id]
            amount = actual_damage * mine.ally_heal_on_hit_pct / 100
            if hurt and round(amount) > 0 and self._spend(player, "ally_heal"):
                ally = min(hurt, key=lambda m: m["hp"] / max(1, m["max_hp"]))
                mended = self._heal(player, ally, amount, allow_buff=False)
                if mended:
                    action_text += f" ✚ {ally['name']} +{mended}"

        if (mine.lifesteal_pct > 0 and round(actual_damage * mine.lifesteal_pct / 100) > 0  # Vampire
                and player["hp"] < player["max_hp"] and self._spend(player, "lifesteal")):
            stolen = self._heal(player, player, actual_damage * mine.lifesteal_pct / 100,
                           allow_buff=False)
            if stolen:
                action_text += f" 🧛 +{stolen}"
        # Soif écarlate : un critique soigne de 20 % des dégâts infligés.
        if (crit and mine.has("scarlet_thirst") and round(actual_damage * 0.20) > 0
                and player["hp"] < player["max_hp"] and self._spend(player, "scarlet_thirst")):
            drunk = self._heal(player, player, actual_damage * 0.20, allow_buff=False)
            if drunk:
                action_text += f" 🍷 +{drunk}"

        # Vaillant : seulement s'il y a un allié à protéger et qu'aucune
        # provocation n'attend déjà le prochain coup des ennemis — elle ne
        # vaut que pour celui-là : la reprendre gaspillait le mana (trois
        # Vaillant se la volaient en boucle, mesuré le 25/10/2026).
        if (mine.taunt_chance_pct > 0 and not self._taunters() and self._has_allies(player)
                and random.random() < mine.taunt_chance_pct / 100 and self._spend(player, "taunt")):
            self._provoke(player)
            action_text += " 🫀 provoque"

        if E["reflect_pct"] > 0 and actual_damage > 0:
            reflected = max(1, round(actual_damage * E["reflect_pct"] / 100))
            self._apply_player_damage(player, reflected, use_shield=False)
            self._emit("hit", self.pk(player), reflected, source=self.ek(E), style="reflect")
            action_text += f" (renvoi {reflected})"

        # Contrecoup : la DEF du monstre en trop revient au joueur (coup
        # arrivé sur l'armure, immunité comprise ; pas sur une esquive).
        if recoil > 0 and (landed or immune):
            taken = self._apply_player_damage(player, recoil, use_shield=False)
            self._emit("recoil", self.pk(player), taken, source=self.ek(E))
            action_text += f" (🔁 {taken} en contrecoup" + (" 💀)" if player["hp"] <= 0 else ")")

        # Effets posés sur l'ennemi (passifs d'équipement, non cumulables
        # entre porteurs sauf la brûlure).
        if actual_damage > 0 and E["hp"] > 0:
            if mine.has("root_venom"):   # Sève vénéneuse
                venom = max(1, min(round(E["max_hp"] * ROOT_VENOM_PCT / 100),
                                   round(stats.attack * ROOT_VENOM_ATK_CAP_PCT / 100)))
                if E["poison"] is None or venom >= E["poison"]["dmg"]:
                    E["poison"] = {"dmg": venom, "turns": 3, "by": player["player_id"]}
                else:
                    E["poison"]["turns"] = 3
                action_text += " 🐍"
            if mine.has("crushing_paw") and E["armor_break"] < 15:   # Coup de patte brisant
                E["armor_break"] = min(15, E["armor_break"] + 3)
                action_text += f" 🐾−{E['armor_break']}%"
            if mine.has("astral_grip") and E["slow_pct"] < 25:   # Étreinte astrale
                E["slow_pct"] = min(25, E["slow_pct"] + 5)
                action_text += f" 🐙−{E['slow_pct']}%"
            if crit and mine.has("lingering_ember"):   # Braise persistante
                E["atk_down"] = 2
                E["burns"].append({"dmg": max(1, round(actual_damage * 0.10)), "turns": 2,
                                   "by": player["player_id"]})
                action_text += " 🔥"
            if waltz and len(E["bleeds"]) < 3:   # Valse sanglante
                E["bleeds"].append({"dmg": max(1, round(actual_damage * 0.10)), "turns": 3,
                                    "by": player["player_id"]})
                action_text += " 🩸"

        # Dégâts de zone (AOE) : une part du coup frappe les voisins de la cible.
        if mine.splash_damage_pct > 0 and actual_damage > 0 and not chained:
            splashed = [
                f"{N['mob'].name} −{dealt}"
                for N in self._neighbours(E)
                if (dealt := self._hurt_foe(N, max(1, round(actual_damage * mine.splash_damage_pct / 100)),
                                       player, style="splash"))
            ]
            if splashed:
                action_text += " 🔮 " + ", ".join(splashed)

        # Souffle ancestral : exécute une cible (hors boss) sous 20 % de PV.
        if (landed and mine.has("ancestral_breath") and 0 < E["hp"] < E["max_hp"] * 0.20
                and not E["is_boss"] and self._spend(player, "ancestral_breath")):
            self.contributions[player["player_id"]].damage_dealt += E["hp"]
            self._emit("execute", self.ek(E), E["hp"], source=self.pk(player))
            E["hp"] = 0
            action_text += " 🐉 exécuté !"

        action_text += self._dry_note(player)
        self.turn_logs.append(self.snap(mob_action_text, players=[action_text], focus=E))
        self._check_mob_thresholds(E)
        return actual_damage

    def _resolve_mob_hit(
        self, mob, target, contributions, title_bonuses_by_player,
        incoming_mult_by_player, mob_family,
        extra_multiplier: float = 1.0, force_crit: bool = False, can_dodge: bool = True,
        attack_override: int | None = None, is_aoe: bool = False,
    ) -> tuple[int, bool, bool]:
        """Coup d'un ennemi sur un joueur (`damage_formula` : crit AVANT
        défense, puis bouclier, puis PV). `attack_override` = attaque
        effective (furie/résurrection). Renvoie (dégâts, crit, esquivé) ; le
        contrecoup éventuel est posé dans `target["_recoil"]` (et le Miroir
        d'éclipse dans `target["_mirror"]`, la Morsure du givre dans
        `target["_freeze"]`), à appliquer à l'ennemi par l'appelant."""
        tstats: Stats = target["stats"]
        gear = self._p(target)

        dodge = tstats.dodge
        if gear.has("night_flight") and target["hp"] > target["max_hp"] * 0.5:
            dodge += 5   # Vol nocturne
        if can_dodge and dodge > 0 and random.random() < (dodge / 100):
            contributions[target["player_id"]].dodges += 1
            if gear.has("shadow_step"):
                target["shadow"] = True
                target["shadow_guard"] = True
            if gear.has("bloody_waltz"):
                target["waltz"] = True
            return 0, False, True

        # Garde de l'exil : la première attaque reçue est annulée.
        if gear.has("first_hit_ward") and not target.get("warded"):
            target["warded"] = True
            if self._spend(target, "first_hit_ward"):
                target["_ward"] = True
                return 0, False, False
        # Échos du vide : l'écho absorbe le coup suivant.
        if target.get("void_ward"):
            target["void_ward"] = False
            target["_ward"] = True
            return 0, False, False

        raw_attack = mob.attack if attack_override is None else attack_override
        raw_attack = max(1, int(raw_attack * getattr(self, "_mob_atk_mult", 1.0)))  # Cri affaiblissant
        crit = force_crit or (random.random() < (mob.crit_chance / 100))
        if crit:
            raw_attack = int(raw_attack * (mob.crit_damage / 100))
        if extra_multiplier != 1.0:
            raw_attack = int(raw_attack * extra_multiplier)

        defense = tstats.defense
        if gear.has("stone_skin") and target.get("stone"):
            defense = round(defense * (1 + min(20, target["stone"]) / 100))
        if target.get("armor_break"):
            defense = round(defense * (1 - target["armor_break"] / 100))
        after_defense, recoil = resolve_hit(raw_attack, defense)
        target["_recoil"] = thorns_recoil(recoil, gear.has("thorns"))
        if gear.has("stone_skin"):
            target["stone"] = target.get("stone", 0) + 1

        tb = title_bonuses_by_player.get(target["player_id"])
        if tb is not None and mob_family:
            mob_damage = max(1, round(after_defense * tb.damage_received_multiplier_from(mob_family)))
        else:
            mob_damage = after_defense

        incoming_mult = incoming_mult_by_player.get(target["player_id"], 1.0)
        if incoming_mult <= 0:
            mob_damage = 0  # résistance élémentaire ≥ 100 % : immunisé
        elif incoming_mult != 1.0:
            mob_damage = max(1, round(mob_damage * incoming_mult))

        if mob_damage > 0:
            mult = 1.0
            if crit and gear.has("crit_ward"):
                mult *= 0.75
            if is_aoe and gear.has("blast_ward"):
                mult *= 0.50
            if target.get("shadow_guard"):
                mult *= 0.90
                target["shadow_guard"] = False
            if target.get("taunt_guard"):  # Défi : −15 % tant que la provocation dure
                mult *= 0.85
                target["taunt_guard"] = False
            mult *= self._oath_multiplier(target)
            if mult != 1.0:
                mob_damage = max(1, round(mob_damage * mult))

        mob_damage = self._reduced(target, mob_damage) if mob_damage > 0 else 0

        # Rempart : un allié encaisse une part du coup à la place de la cible.
        guard = self._guardian_for(target)
        if guard is not None and mob_damage > 0:
            portion = int(round(mob_damage * self._p(guard).redirect_ally_damage_pct / 100))
            if portion > 0 and self._spend(guard, "redirect"):
                mob_damage -= portion
                taken = self._apply_player_damage(guard, self._reduced(guard, portion))
                self._emit("hit", f"p{guard['player_id']}", taken, style="guard")
                contributions[guard["player_id"]].damage_tanked += portion
                target["_redirected"] = (guard["name"], taken)

        dealt = self._apply_player_damage(target, mob_damage)
        contributions[target["player_id"]].damage_tanked += raw_attack
        if mob_damage > 0:
            if gear.has("eclipse_mirror"):   # Miroir d'éclipse
                target["_mirror"] = max(1, round(mob_damage * 0.15))
            if gear.has("frost_bite") and random.random() < 0.15:   # Morsure du givre
                target["_freeze"] = True
        return dealt, crit, False

    def _pvp_hit(self, attacker, target, contributions) -> tuple[int, bool, bool, int]:
        """Coup joueur → joueur (charme) : même formule (crit AVANT défense,
        puis bouclier, puis PV), contrecoup compris. Renvoie (dégâts, crit,
        esquivé, contrecoup subi par l'attaquant)."""
        astats: Stats = attacker["stats"]
        tstats: Stats = target["stats"]

        if tstats.dodge > 0 and random.random() < (tstats.dodge / 100):
            contributions[target["player_id"]].dodges += 1
            return 0, False, True, 0

        raw = astats.attack
        crit = random.random() < (astats.crit_chance / 100)
        if crit:
            raw = int(raw * (astats.crit_damage / 100))
        dmg, recoil = resolve_hit(raw, tstats.defense)
        dmg = self._reduced(target, dmg)
        dmg = self._apply_player_damage(target, dmg)
        contributions[target["player_id"]].damage_tanked += raw
        recoil = thorns_recoil(recoil, self._p(target).has("thorns"))
        taken = self._apply_player_damage(attacker, recoil, use_shield=False) if recoil else 0
        return dmg, crit, False, taken
