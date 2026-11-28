"""Le GROUPE de joueurs : passifs, ciblage et aggro, provocation, soins et
boucliers, mana, dégâts encaissés, effets sur la durée.

Méthodes de `PartyCombatService` (mixin), sorties de
`party_combat_service.py` le 28/11/2026 (audit) : texte inchangé. L'état
du combat en cours vit sur l'instance (une par combat)."""

import random
from dataclasses import replace

from app.domain.services.combat_passives import (
    HEAL_BELOW_PCT,
    MANA_ABILITY_NAMES,
    MANA_COSTS,
    NO_PASSIVES,
    CombatPassives,
    normalize_tactic,
)


from app.domain.services.party_combat_rules import THREAT_DEF_WEIGHT, THREAT_EXPONENT


class PartyMixin:
    def P(self, member) -> CombatPassives:
        return self.passives_by_player.get(member["player_id"], NO_PASSIVES)

    def pk(self, member) -> str:
        return f"p{member['player_id']}"

    def ek(self, E) -> str:
        return f"e{E['i']}"

    def _player_target(self):
        """L'ennemi le plus ABÎMÉ (part de PV la plus basse) : on se
        concentre. Les gardes d'un boss passent avant lui."""
        living = self._living_foes()
        if not living:
            return None
        if self._guards_up():
            living = [E for E in living if E["guard"]]
        return min(living, key=lambda E: (E["hp"] / max(1, E["max_hp"]), E["i"]))

    def _charmed_member(self):
        return next((p for p in self.alive_party if p["player_id"] == self.charmed_id), None)

    def _charmed_alive(self) -> bool:
        m = self._charmed_member()
        return m is not None and m["hp"] > 0

    def _party_alive(self) -> bool:
        if self.escort and any(p["hp"] <= 0 for p in self.alive_party if p["player_id"] in self.escort):
            return False
        return any(p["hp"] > 0 and p["player_id"] != self.charmed_id and not p["absorbed"]
                   for p in self.alive_party)

    def _mob_targets(self) -> list:
        return [p for p in self.alive_party
                if p["hp"] > 0 and p["player_id"] != self.charmed_id and not p["absorbed"]
                and (not self.escort or p["player_id"] in self.escort)]

    # ── Passifs : soins, provocation (cf. combat_passives) ──
    def _taunters(self) -> set[int]:
        return {E["taunted_by"] for E in self.foes if E["hp"] > 0 and E["taunted_by"] is not None}

    def _provoke(self, member) -> None:
        """Provocation : la PROCHAINE attaque de chaque ennemi le vise."""
        for E in self._living_foes():
            E["taunted_by"] = member["player_id"]

    def _buff(self, member, pct: float) -> None:
        if member["buffed"] or pct <= 0:
            return
        st = member["stats"]
        member["stats"] = replace(
            st,
            attack=max(1, round(st.attack * (1 + pct / 100))),
            defense=max(0, round(st.defense * (1 + pct / 100))),
        )
        member["buffed"] = True

    def _heal(self, healer, target, amount: float, allow_buff: bool = True) -> int:
        """Soigne `target` : soins reçus (Paladin), Buff (cible + soigneur).
        Seuls les soins donnés aux ALLIÉS comptent dans la contribution.
        Mains guérisseuses : soins donnés +10 %, et 10 % des soins donnés à
        un allié frappent l'ennemi. Pas de l'ombre : prochain soin +10 %.
        Ramure bienveillante : +15 % de soins reçus pour tout le groupe
        (une seule aura)."""
        if amount <= 0 or target["hp"] <= 0:
            return 0
        if self.P(healer).has("healing_hands"):
            amount *= 1.10
        if allow_buff and healer["shadow"]:
            amount *= 1.10
            healer["shadow"] = False
        amount *= 1 + self.P(target).heal_received_pct / 100
        if any(self.P(m).has("kind_antlers") and m["hp"] > 0 for m in self.alive_party):
            amount *= 1.15
        before = target["hp"]
        target["hp"] = min(target["max_hp"], target["hp"] + int(round(amount)))
        healed = target["hp"] - before
        if healed > 0:
            self._emit("heal", self.pk(target), healed, source=self.pk(healer))
        if healer["player_id"] != target["player_id"]:
            self.contributions[healer["player_id"]].hp_healed += healed
            if self.P(healer).has("healing_hands") and healed > 0 and self._foes_alive():
                self._hurt_foe(self._player_target(), max(1, round(healed * 0.10)), healer, style="holy")
        if allow_buff and self.P(healer).heal_buff_pct > 0:
            self._buff(target, self.P(healer).heal_buff_pct)
            self._buff(healer, self.P(healer).heal_buff_pct)
        return healed

    def _heal_target(self, healer):
        """Cible du sort de soin selon la tactique (figée pour le combat),
        parmi les alliés sous `HEAL_BELOW_PCT` % de leurs PV."""
        team = [m for m in self.alive_party
                if m["hp"] > 0 and not m["absorbed"] and m["player_id"] != self.charmed_id]
        injured = [m for m in team if m["hp"] < m["max_hp"] * HEAL_BELOW_PCT / 100]
        if not injured:
            return None
        tactic = normalize_tactic(self.tactics_by_player.get(healer["player_id"]))
        if tactic == "egoiste":
            if healer in injured:
                return healer
            return min(injured, key=lambda m: m["hp"] / max(1, m["max_hp"]))
        metric = "damage_tanked" if tactic == "pragmatique" else "damage_dealt"
        return max(injured, key=lambda m: (
            getattr(self.contributions[m["player_id"]], metric),
            -(m["hp"] / max(1, m["max_hp"])),
        ))

    def _single_target(self, pool, E):
        """Cible d'une attaque mono-cible : le provocateur s'il peut être
        frappé (Vaillant), sinon selon l'aggro (cf. THREAT_EXPONENT)."""
        if E["taunted_by"] is not None:
            forced = next((m for m in pool if m["player_id"] == E["taunted_by"]), None)
            if forced is not None:
                return forced
        weights = [
            ((m["stats"].max_hp + m["stats"].defense * THREAT_DEF_WEIGHT)
             * (1 + self.P(m).threat_pct / 100)) ** THREAT_EXPONENT   # Gardien
            for m in pool
        ]
        return random.choices(pool, weights=weights, k=1)[0]

    def _aura_pct(self) -> float:
        """Aura du Soigneur : +X % de dégâts pour toute l'équipe tant qu'il
        est debout. UNE seule aura par équipe (la plus forte), même avec
        plusieurs Soigneurs."""
        return max(
            (self.P(m).team_damage_pct for m in self.alive_party
             if m["hp"] > 0 and not m["absorbed"] and m["player_id"] != self.charmed_id),
            default=0.0,
        )

    def _living_allies(self, member) -> int:
        return sum(1 for m in self.alive_party
                   if m is not member and m["hp"] > 0 and not m["absorbed"]
                   and m["player_id"] != self.charmed_id)

    def _has_allies(self, member) -> bool:
        return any(m is not member and m["hp"] > 0 and not m["absorbed"]
                   and m["player_id"] != self.charmed_id for m in self.alive_party)

    def _tick_dots(self, p) -> None:
        """Saignement (ogre) et poison : UNE fois par action de la victime.

        Avant (audit oct. 2026) ils tombaient à chaque TICK de jauge, soit
        ~10-20 fois par action : un poison « 3 tours » durait 3 ticks, se
        renouvelait à chaque coup et doublait les dégâts du monstre — et
        chaque tick comptait comme une action (escalade avancée)."""
        lines = []
        pz = p.get("poison")
        if pz:
            self._apply_player_damage(p, pz["dmg"], use_shield=False)
            self._emit("dot", self.pk(p), pz["dmg"], style="poison")
            self.contributions[p["player_id"]].damage_tanked += pz["dmg"]
            lines.append(f"☠️ Poison : {p['name']} −{pz['dmg']}")
            pz["turns"] -= 1
            if pz["turns"] <= 0:
                p["poison"] = None
        if p["bleeds"] and p["hp"] > 0:
            total = sum(b["dmg"] for b in p["bleeds"])
            self._apply_player_damage(p, total, use_shield=False)
            self._emit("dot", self.pk(p), total, style="bleed")
            self.contributions[p["player_id"]].damage_tanked += total
            lines.append(f"🩸 Saignement : {p['name']} −{total}")
            for b in p["bleeds"]:
                b["turns"] -= 1
            p["bleeds"] = [b for b in p["bleeds"] if b["turns"] > 0]
        if lines:
            self.turn_logs.append(self.snap(" · ".join(lines) + (" 💀" if p["hp"] <= 0 else "")))

    def _member(self, player_id):
        return next((m for m in self.alive_party if m["player_id"] == player_id), None)

    def _void_echo(self, player) -> None:
        """Échos du vide : toutes les 8 actions, un écho frappe la cible
        (50 % de l'ATK, sans défense) et absorbe le prochain coup reçu."""
        if (not self.P(player).has("void_echo") or player["actions"] % 8 or not self._foes_alive()
                or not self._spend(player, "void_echo")):
            return
        target = self._player_target()
        dealt = self._hurt_foe(target, max(1, round(player["stats"].attack * 0.50)), player, style="void")
        player["void_ward"] = True
        self.turn_logs.append(self.snap(f"🌀 Écho du vide de {player['name']} : {target['mob'].name} −{dealt}, "
                              f"le prochain coup reçu sera absorbé.", focus=target))

    def _oath_multiplier(self, target) -> float:
        """Serment du gardien : tant qu'il provoque, son porteur subit 20 %
        de dégâts en moins et ses alliés 10 % (le plus fort s'applique)."""
        taunters = {E["taunted_by"] for E in getattr(self, "_foes", [])
                    if E["hp"] > 0 and E["taunted_by"] is not None}
        if not taunters:
            return 1.0
        if target["player_id"] in taunters and self._p(target).has("guardian_oath"):
            return 0.80
        for m in getattr(self, "_party", None) or []:
            if (m is not target and m["hp"] > 0 and m["player_id"] in taunters
                    and self._p(m).has("guardian_oath")):
                return 0.90
        return 1.0

    def _p(self, member) -> CombatPassives:
        return getattr(self, "_passives", {}).get(member["player_id"], NO_PASSIVES)

    def _spend(self, member, ability: str) -> bool:
        """Prélève le mana d'une compétence active (cf. MANA_COSTS). Réserve
        abyssale : −20 %. À court de mana, le Pacte de sang paie en PV (5 %
        des PV max, et les PV max baissent de 5 % pour le combat) ; sinon
        l'effet n'a pas lieu."""
        cost = getattr(self, "_mana_costs", MANA_COSTS).get(ability, 0)
        if cost > 0 and self._p(member).has("abyssal_reserve"):
            cost = max(1, round(cost * 0.80))
        contrib = getattr(self, "_contribs", {}).get(member["player_id"])
        if member.get("mana", 0) < cost:
            price = max(1, round(member.get("max_hp", 0) * 0.05))
            if self._p(member).has("blood_pact") and member.get("hp", 0) > price:
                member["hp"] -= price
                member["max_hp"] = max(1, round(member["max_hp"] * 0.95))
                member["hp"] = min(member["hp"], member["max_hp"])
                member["_blood"] = True
                if contrib is not None:
                    contrib.mana_uses[ability] = contrib.mana_uses.get(ability, 0) + 1
                return True
            if contrib is not None:
                contrib.mana_dry += 1
            if not member.get("dry_noted"):
                member["dry_noted"] = True
                member["_dry"] = MANA_ABILITY_NAMES.get(ability, ability)
            return False
        member["mana"] = member.get("mana", 0) - cost
        if contrib is not None:
            contrib.mana_spent += cost
            contrib.mana_uses[ability] = contrib.mana_uses.get(ability, 0) + 1
        return True

    def _reduced(self, member, damage: int) -> int:
        """Réductions des dégâts reçus (Résistant, Titan…), additionnées."""
        frac = self._p(member).damage_reduction_fraction
        return max(1, round(damage * (1 - frac))) if frac > 0 and damage > 0 else damage

    def _guardian_for(self, target):
        """Le Rempart vivant qui protège `target` (jamais lui-même)."""
        party = getattr(self, "_party", None) or []
        guards = [m for m in party
                  if m is not target and m["hp"] > 0 and not m.get("absorbed")
                  and self._p(m).redirect_ally_damage_pct > 0]
        return max(guards, key=lambda m: self._p(m).redirect_ally_damage_pct, default=None)

    def _apply_player_damage(self, member, damage: int, use_shield: bool = True) -> int:
        """Bouclier puis PV ; Tenace laisse à 1 PV le premier coup fatal.
        Renvoie les dégâts retirés aux PV (après bouclier), comme avant.
        Mousse vivace (sous 30 %), Revenant, Grâce brisée et Dévoration se
        déclenchent ici."""
        if damage <= 0:
            return 0
        if use_shield and member.get("shield", 0) > 0:
            absorbed = min(member["shield"], damage)
            member["shield"] -= absorbed
            damage -= absorbed
        if (damage >= member["hp"] > 0 and self._p(member).last_stand
                and not member.get("last_stand_used") and self._spend(member, "last_stand")):
            member["last_stand_used"] = True
            member["_held"] = True
            self._emit("hold", f"p{member['player_id']}")
            damage = member["hp"] - 1
        member["hp"] = max(0, member["hp"] - damage)
        # Revenant : la première mort ramène à 50 % des PV.
        if (member["hp"] <= 0 and self._p(member).has("undying") and not member.get("gear_revived")
                and self._spend(member, "undying")):
            member["gear_revived"] = True
            member["hp"] = max(1, member["max_hp"] // 2)
            member["_revived"] = True
            self._emit("revive", f"p{member['player_id']}")
        party = getattr(self, "_party", None) or []
        if member["hp"] <= 0 and not member.get("dead_noted"):
            # Grâce brisée : le premier allié qui tombe se relève à 30 % (une
            # fois par porteur et par combat).
            saviour = None
            if not member.get("charmed"):
                saviour = next((m for m in party
                                if m is not member and m["hp"] > 0 and not m.get("absorbed")
                                and self._p(m).has("broken_grace") and not m.get("grace_used")
                                and self._spend(m, "broken_grace")), None)
            if saviour is not None:
                saviour["grace_used"] = True
                member["hp"] = max(1, round(member["max_hp"] * 0.30))
                member["_graced"] = saviour["name"]
                self._emit("revive", f"p{member['player_id']}", source=f"p{saviour['player_id']}")
            else:
                member["dead_noted"] = True
                self._emit("ko", f"p{member['player_id']}")
                # Dévoration : chaque allié qui meurt donne 10 % de son ATK, de
                # sa DEF et de ses PV max au porteur, pour le combat.
                for m in party:
                    if m is member or m["hp"] <= 0 or not self._p(m).has("devour"):
                        continue
                    gained_hp = max(0, round(member["max_hp"] * 0.10))
                    m["stats"] = replace(
                        m["stats"],
                        attack=m["stats"].attack + round(member["stats"].attack * 0.10),
                        defense=m["stats"].defense + round(member["stats"].defense * 0.10),
                    )
                    m["max_hp"] += gained_hp
                    m["hp"] += gained_hp
        # Mousse vivace : la première fois sous 30 % de PV, 10 % des PV max à
        # chacune des 7 actions suivantes.
        if (0 < member["hp"] < member["max_hp"] * 0.30 and self._p(member).has("verdant_moss")
                and not member.get("moss_used") and self._spend(member, "verdant_moss")):
            member["moss_used"] = True
            member["moss"] = 7
            member["_moss"] = True
        return damage
