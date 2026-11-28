"""Moteur de combat de groupe : un ou plusieurs joueurs contre un ou plusieurs
ennemis (zones, tour, world boss, épreuves, défis — partout le même).

Organisation (découpage du 28/11/2026, comportement inchangé : 2 346 combats
témoins identiques à l'octet près avant / après) :
  • ici, `fight_party_vs_mob(s)` : préparation, boucle des actions, résultat ;
  • `party_combat_rules` : réglages (escalade, aggro…), `EnemySetup` ;
  • `party_combat_foes`  : les ennemis (état, phases, gardes, mort…) ;
  • `party_combat_party` : le groupe (ciblage, soins, mana, dégâts encaissés) ;
  • `party_combat_strike` : les coups (joueur, monstre, allié charmé) ;
  • `party_combat_log`   : journal et événements dessinés.
Une instance par combat : l'état du combat en cours (ennemis, groupe,
journal, actions…) vit sur `self` le temps du combat.
"""

import random
from dataclasses import replace

from app.domain.entities.element_skill import (
    SKILL_KIND_DAMAGE,
    SKILL_KIND_HEAL_ALLY,
    SKILL_KIND_SHIELD_SELF,
    SKILL_KIND_SHIELD_TEAM,
)
from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.combat_passives import (
    BASE_HEAL_PCT,
    MANA_COSTS,
    CombatPassives,
)
from app.domain.services.damage_formula import resolve_hit
from app.domain.services.power_score_service import PowerScoreService
from app.domain.services.skill_effect_service import SkillEffectService
from app.domain.services.title_bonus_service import TitleBonuses
from app.domain.value_objects.party_battle_result import PartyBattleResult
from app.domain.value_objects.party_battle_turn_log import PartyBattleTurnLog
from app.domain.value_objects.player_contribution import PlayerContribution
from app.domain.value_objects.stats import Stats
from app.domain.services.party_combat_rules import (  # noqa: F401 — réexportés
    ESCALATION_START,
    ESCALATION_EVERY,
    ESCALATION_STEP,
    HARD_MAX_TURNS,
    THREAT_DEF_WEIGHT,
    THREAT_EXPONENT,
    ROOT_VENOM_PCT,
    ROOT_VENOM_ATK_CAP_PCT,
    escalation_multiplier,
    EnemySetup,
    ULTIMATE_SINGLE_MULT,
)
from app.domain.services.party_combat_foes import FoesMixin
from app.domain.services.party_combat_party import PartyMixin
from app.domain.services.party_combat_strike import StrikeMixin
from app.domain.services.party_combat_log import LogMixin


class PartyCombatService(FoesMixin, PartyMixin, StrikeMixin, LogMixin):
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
        passives_by_player: dict[int, CombatPassives] | None = None,
        tactics_by_player: dict[int, str] | None = None,
        mob_is_boss: bool = False,
        max_ticks: int = 0,
        escort_ids: set[int] | frozenset[int] | None = None,
        mana_costs: dict[str, int] | None = None,
    ) -> PartyBattleResult:
        """Combat contre UN monstre : un groupe d'ennemis réduit à un seul."""
        enemy = EnemySetup(
            mob=mob,
            abilities=mob_abilities or {},
            elemental_out=elemental_mult_by_player or {},
            elemental_in=incoming_elemental_mult_by_player or {},
            is_boss=mob_is_boss,
            immunity_threshold=damage_immunity_threshold,
            heal_per_turn=boss_heal_per_turn,
            reflect_pct=boss_reflect_pct,
            adds=boss_adds,
        )
        return self.fight_party_vs_mobs(
            party, [enemy],
            title_bonuses_by_player=title_bonuses_by_player,
            skill_loadouts_by_player=skill_loadouts_by_player,
            max_turns=max_turns,
            passives_by_player=passives_by_player,
            tactics_by_player=tactics_by_player,
            max_ticks=max_ticks,
            escort_ids=escort_ids,
            mana_costs=mana_costs,
        )

    def fight_party_vs_mobs(
        self,
        party: list[dict],
        enemies: list[EnemySetup],
        title_bonuses_by_player: dict[int, TitleBonuses] | None = None,
        skill_loadouts_by_player: dict | None = None,
        max_turns: int = 0,
        passives_by_player: dict[int, CombatPassives] | None = None,
        tactics_by_player: dict[int, str] | None = None,
        max_ticks: int = 0,
        escort_ids: set[int] | frozenset[int] | None = None,
        mana_costs: dict[str, int] | None = None,
    ) -> PartyBattleResult:
        """Combat d'un groupe de joueurs contre un ou plusieurs ennemis (27/10/2026).

        Les joueurs frappent l'ennemi le plus ABÎMÉ (part de PV la plus basse,
        le premier de la formation à égalité) : ils se concentrent. Les dégâts
        de zone (AOE de l'arbre) touchent les ennemis VOISINS de la cible dans
        la formation (l'ordre de `enemies`). Chaque ennemi a sa jauge, ses
        capacités, son escalade et sa provocation à lui.

        max_ticks  : limite de TEMPS (ticks de jauge) plutôt que d'actions —
                     la vitesse compte (épreuve DPS : « 40 s de combat »).
        escort_ids : les ennemis ne visent QUE ces joueurs, et le combat
                     s'arrête dès que l'un d'eux tombe (épreuve de soutien).
        mana_costs : coûts des compétences actives (défaut MANA_COSTS ; les
                     outils de mesure passent {} pour compter sans limite)."""
        self.passives_by_player = passives_by_player
        self.tactics_by_player = tactics_by_player
        self.title_bonuses_by_player = title_bonuses_by_player
        self.title_bonuses_by_player = self.title_bonuses_by_player or {}
        skill_loadouts_by_player = skill_loadouts_by_player or {}
        self.passives_by_player = self.passives_by_player or {}
        self.tactics_by_player = self.tactics_by_player or {}
        self._passives = self.passives_by_player
        self._mana_costs = MANA_COSTS if mana_costs is None else mana_costs
        # Événements de l'action en cours (chiffres et effets dessinés sur la
        # scène) : vidés dans chaque instantané du journal. Pur enregistrement,
        # aucun tirage — le combat est identique avec ou sans affichage.
        self._events: list[dict] = []
        _skill_svc = SkillEffectService()
        hard_max = HARD_MAX_TURNS * max(1, len(enemies))


        self.turns = 0
        self.turn_logs: list[PartyBattleTurnLog] = []

        self.alive_party = [
            {
                "player_id": player["player_id"],
                "user_id": player["user_id"],
                "name": player["name"],
                "avatar_url": player["avatar_url"],
                "stats": player["stats"],
                "hp": player["current_hp"],
                "max_hp": player["max_hp"],
                # Mana courant inconnu ⇒ réserve pleine.
                "mana": player.get("current_mana", player.get("mana_max", player["stats"].mana_max)),
                "mana_max": player.get("mana_max", player["stats"].mana_max),
                "gauge": 0,
                "shield": 0,        # bouclier (compétences défensives/support)
                "stunned": False,   # étourdi (gobelin géant / banshee)
                "slow": 0,          # stacks de ralentissement (momie)
                "bleeds": [],       # saignements actifs (ogre) : [{dmg, turns}]
                "poison": None,     # empoisonnement : {dmg, turns} (non cumulable)
                "armor_break": 0,   # % de DEF brisée pour le combat (plafonné)
                "absorbed": False,  # englouti par le slime → hors combat
                "absorbed_by": None,  # index de l'ennemi qui l'a englouti
                "charmed": False,   # retourné par une succube
                "last_stand_used": False,  # Tenace : déjà sauvé une fois
                "buffed": False,           # Buff de soin déjà reçu (non cumulable)
                # Passifs d'équipement (cf. gear_passives)
                "opened": False,           # a déjà porté sa 1re attaque
                "warded": False,           # 1re attaque reçue déjà annulée
                "gear_revived": False,     # Revenant déjà utilisé
                "fury": 0,                 # Fureur montante : attaques portées
                "stone": 0,                # Peau de pierre : coups subis
                "shadow": False,           # Pas de l'ombre : prochaine action +10 %
                "shadow_guard": False,     # Pas de l'ombre : prochain coup reçu −10 %
                "taunt_guard": False,      # Défi : −15 % tant que la provocation dure
                "storm_used": False,       # Œil de la tempête : déjà déchaîné
                "dived": False,            # Piqué : déjà porté
                "attacks": 0,              # attaques portées (Souffle juvénile)
                "actions": 0,              # actions jouées (Échos du vide)
                "void_ward": False,        # Échos du vide : prochain coup reçu absorbé
                "void_hits": 0,            # Néant dévorant : coups portés
                "waltz": False,            # Valse sanglante : a esquivé, coup suivant critique
                "moss": 0,                 # Mousse vivace : tours de soin restants
                "moss_used": False,
                "grace_used": False,       # Grâce brisée : a déjà relevé un allié
                "dead_noted": False,       # sa chute a été comptée (Dévoration)
            }
            for player in party
        ]

        self._party = self.alive_party
        # Effets sur l'ennemi : UN exemplaire actif, quel que soit le nombre
        # de porteurs (dix joueurs à −5 % d'ATK, ça reste −5 %).
        anti_heal = any(self.P(m).has("anti_heal") for m in self.alive_party)
        self._mob_atk_mult = 0.95 if any(self.P(m).has("weakening_cry") for m in self.alive_party) else 1.0
        self.contributions: dict[int, PlayerContribution] = {
            member["player_id"]: PlayerContribution(
                player_id=member["player_id"],
                user_id=member["user_id"],
                name=member["name"],
                max_hp=member["max_hp"],
                final_hp=member["hp"],
                mana_max=member["mana_max"],
            )
            for member in self.alive_party
        }
        self._contribs = self.contributions


        self.foes = [self._foe(i, setup) for i, setup in enumerate(enemies)]
        self._foes = self.foes


        self.decisive_foes = [E for E in self.foes if E["decisive"]]


        # ── État du charme (succube) ──
        self.charmed_id: int | None = None
        self.charm_foe = None
        _power = PowerScoreService()


        self.escort = frozenset(escort_ids or ())


        # ─── Phases déjà franchies (PV d'un boss conservés d'un assaut à l'autre)
        for E in self.foes:
            ratio = E["hp"] / max(1, E["max_hp"]) * 100
            for phase in E["phases"]:
                if ratio <= float(phase.get("below_pct", 0)):
                    self._activate_phase(E, phase, announce=False)

        # ─── Début du combat : vitesse par allié (Soigneur), boucliers (Égide) ───
        allies_count = max(0, len([m for m in self.alive_party if m["hp"] > 0]) - 1)
        for m in self.alive_party:
            if self.P(m).speed_per_ally and allies_count:
                m["stats"] = replace(m["stats"], speed=m["stats"].speed + self.P(m).speed_per_ally * allies_count)
        shield_lines = []
        for caster in self.alive_party:
            pct = self.P(caster).team_shield_pct
            if pct <= 0 or caster["hp"] <= 0 or not self._spend(caster, "team_shield"):
                continue
            amount = int(round(caster["max_hp"] * pct / 100))
            for m in self.alive_party:
                if m["hp"] <= 0:
                    continue
                m["shield"] += amount
                self._emit("shield", self.pk(m), amount, source=self.pk(caster))
                if m["player_id"] != caster["player_id"]:
                    self.contributions[caster["player_id"]].hp_healed += amount
            shield_lines.append(f"{caster['name']} ({amount})")
        if shield_lines:
            self.turn_logs.append(self.snap("🗿 Égide : bouclier pour tout le groupe — " + " · ".join(shield_lines)))

        round_count = 0

        # ─── Frappe d'ouverture prioritaire (assassin) ───
        for E in self.foes:
            if "opening_assassinate" not in E["ab"] or E["hp"] <= 0:
                continue
            streak = 0
            while any(p["hp"] > 0 for p in self.alive_party):
                streak += 1
                target = min((p for p in self.alive_party if p["hp"] > 0),
                             key=lambda p: (p["hp"], p["max_hp"]))
                shield_before = target["shield"]
                dmg, crit, dodged = self._resolve_mob_hit(
                    E["mob"], target, self.contributions, self.title_bonuses_by_player,
                    E["in"], E["family"], extra_multiplier=streak, force_crit=True)
                self._mob_hit_fx(target, E, dmg, crit, dodged, "assassinate", shield_before)
                target.pop("_freeze", None)
                self._recoil_to_mob(target, E)
                self.turns += 1
                if dodged:
                    action = f"⚡ {E['mob'].name} fond sur {target['name']} (assassinat) — esquivé !"
                else:
                    mult = f" ×{streak}" if streak > 1 else ""
                    action = f"⚡ {E['mob'].name} assassine {target['name']} : {dmg} dégâts (CRIT{mult})"
                    if target["hp"] <= 0:
                        action += " — 💀 exécuté !"
                    action += self._tags(target)
                self.turn_logs.append(self.snap(action, focus=E))
                if dodged or target["hp"] > 0 or E["hp"] <= 0:
                    break

        # ─── Défi : le porteur commence en provocation ───
        guard_holder = next((m for m in self.alive_party if self.P(m).has("taunt_guard") and m["hp"] > 0
                             and self._spend(m, "taunt_guard")), None)
        if guard_holder is not None:
            self._provoke(guard_holder)
            guard_holder["taunt_guard"] = True

        # ─── Charme (succube) ─── (Volonté de fer : immunisé)
        self.charm_foe = next((E for E in self.foes if "charm" in E["ab"] and E["hp"] > 0), None)
        if self.charm_foe is not None:
            living = [p for p in self.alive_party if p["hp"] > 0 and not self.P(p).has("iron_will")]
            if not living and any(p["hp"] > 0 for p in self.alive_party):
                self.turns += 1
                self.turn_logs.append(self.snap(f"💋 {self.charm_foe['mob'].name} tente de charmer… "
                                      f"mais aucune volonté ne plie !", focus=self.charm_foe))
            if living:
                charmed = max(living, key=lambda p: _power.calculate_from_stats(p["stats"]))
                self.charmed_id = charmed["player_id"]
                charmed["charmed"] = True
                name = self.charm_foe["mob"].name
                if not self._party_alive():
                    charmed["hp"] = 0
                    action = (f"💋 {name} charme {charmed['name']}… "
                              f"seul et envoûté, il est dévoré ! Défaite.")
                else:
                    action = (f"💋 {name} charme {charmed['name']} (le plus puissant) ! "
                              f"Retourné contre les siens — abattez-le pour atteindre {name}.")
                self.turns += 1
                self.turn_logs.append(self.snap(action, focus=self.charm_foe))

        # ─── Absorption (slime) ───
        # Chance d'engloutir tous les joueurs SAUF le plus fort (jamais si un
        # seul joueur), se renforçant de `stat_pct`% de leurs stats. Relâchés
        # si le slime meurt avant la fin du combat.
        for E in self.foes:
            cfg = E["ab"].get("absorb")
            if not cfg or E["hp"] <= 0:
                continue
            living = [p for p in self.alive_party if p["hp"] > 0 and not p["absorbed"]]
            if len(living) > 1 and random.random() < cfg.get("chance", 10) / 100:
                strongest = max(living, key=lambda p: _power.calculate_from_stats(p["stats"]))
                pct = cfg.get("stat_pct", 50) / 100
                names, gained_hp = [], 0
                for p in living:
                    if p["player_id"] == strongest["player_id"]:
                        continue
                    p["absorbed"] = True
                    p["absorbed_by"] = E["i"]
                    E["bonus_atk"] += p["stats"].attack * pct
                    E["bonus_def"] += p["stats"].defense * pct
                    gained_hp += int(p["max_hp"] * pct)
                    names.append(p["name"])
                E["max_hp"] = E["base"].max_hp + gained_hp
                E["hp"] = min(E["max_hp"], E["hp"] + gained_hp)
                self.turns += 1
                self.turn_logs.append(self.snap(
                    f"🫧 {E['mob'].name} engloutit {', '.join(names)} et absorbe leurs pouvoirs "
                    f"(+{int(E['bonus_atk'])} atk, +{int(E['bonus_def'])} déf, +{gained_hp} PV) !", focus=E))


        while self._foes_alive() and self._party_alive():
            round_count += 1
            if ((max_turns and self.turns >= max_turns) or (max_ticks and round_count > max_ticks)
                    or self.turns >= hard_max):
                break
            for E in self.foes:
                self._escalate(E)

            for player in self.alive_party:
                if player["hp"] > 0 and not player["absorbed"]:
                    fill = player["stats"].speed
                    if self.P(player).has("lunar_rage") and player["hp"] < player["max_hp"] * 0.5:
                        fill = round(fill * 1.15)    # Rage lunaire
                    if player["slow"] > 0:
                        fill = max(1, fill // 2)   # ralenti (momie) : jauge à 50%
                    player["gauge"] += fill

            for E in self._living_foes():
                fill = E["mob"].speed
                if E["slow_pct"]:   # Étreinte astrale
                    fill = max(1, round(fill * (1 - E["slow_pct"] / 100))) if fill > 0 else 0
                E["gauge"] += fill
            acted = False

            for player in self.alive_party:
                while (player["gauge"] >= 100 and player["hp"] > 0 and self._foes_alive()
                       and self.turns < hard_max):
                    self._tick_dots(player)
                    if player["hp"] <= 0:
                        break
                    # Mousse vivace : 10 % des PV max à chacune de ses actions.
                    if player["moss"] > 0:
                        player["moss"] -= 1
                        healed = self._heal(player, player, player["max_hp"] * 0.10, allow_buff=False)
                        if healed:
                            self.turn_logs.append(self.snap(f"🌿 Mousse vivace : {player['name']} +{healed} PV"))
                    # Étourdi : le tour est consommé pour dissiper le statut, sans action.
                    if player["stunned"]:
                        player["stunned"] = False
                        player["gauge"] -= 100
                        if player["slow"] > 0:
                            player["slow"] -= 1
                        self.turns += 1
                        acted = True
                        self.turn_logs.append(self.snap(f"💫 {player['name']} est étourdi et perd son tour."))
                        continue

                    # Charme : le joueur charmé frappe un allié non-charmé.
                    if player["player_id"] == self.charmed_id:
                        prey = [p for p in self.alive_party
                                if p["player_id"] != self.charmed_id and p["hp"] > 0]
                        if not prey:
                            break
                        self.turns += 1
                        acted = True
                        player["gauge"] -= 100
                        if player["slow"] > 0:
                            player["slow"] -= 1
                        victim = random.choice(prey)
                        dmg, crit, dodged, recoil = self._pvp_hit(player, victim, self.contributions)
                        self._emit("dodge" if dodged else ("crit" if crit else "hit"), self.pk(victim), dmg,
                                   source=self.pk(player), style="charm")
                        act = (f"😈 {player['name']} (charmé) attaque {victim['name']} — esquive !"
                               if dodged else
                               f"😈 {player['name']} (charmé) frappe {victim['name']} : {dmg} dégâts"
                               + (" CRIT" if crit else "")
                               + (" 💀" if victim["hp"] <= 0 else "")
                               + (f" (🔁 {recoil} en contrecoup)" if recoil else ""))
                        self.turn_logs.append(self.snap(act))
                        continue

                    self.turns += 1
                    acted = True
                    player["gauge"] -= 100
                    player["actions"] += 1
                    if player["slow"] > 0:
                        player["slow"] -= 1

                    # Charme : les non-charmés doivent d'abord abattre le charmé.
                    if self._charmed_alive():
                        victim = self._charmed_member()
                        dmg, crit, dodged, recoil = self._pvp_hit(player, victim, self.contributions)
                        self._emit("dodge" if dodged else ("crit" if crit else "hit"), self.pk(victim), dmg,
                                   source=self.pk(player), style="slash")
                        freed = victim["hp"] <= 0 and not dodged
                        act = (f"{player['name']} vise {victim['name']} (charmé) — esquive !"
                               if dodged else
                               f"{player['name']} frappe {victim['name']} (charmé) : {dmg} dégâts"
                               + (" CRIT" if crit else "")
                               + (f" (🔁 {recoil} en contrecoup)" if recoil else "")
                               + (f" — 💔 {victim['name']} est libéré !" if freed else ""))
                        self.turn_logs.append(self.snap(act))
                        continue

                    stats: Stats = player["stats"]
                    mine = self.P(player)

                    # Soigneur : le sort de soin REMPLACE l'attaque quand un
                    # allié est sous HEAL_BELOW_PCT % de ses PV ; sinon il attaque
                    # (avant, il soignait dès qu'il manquait 1 PV : seul, il ne
                    # frappait presque jamais).
                    if mine.healer:
                        heal_target = self._heal_target(player)
                        if heal_target is not None and self._spend(player, "heal_spell"):
                            amount = stats.attack * BASE_HEAL_PCT / 100 * mine.heal_power_multiplier
                            healed = self._heal(player, heal_target, amount)
                            who = "se soigne" if heal_target is player else f"soigne {heal_target['name']}"
                            self.turn_logs.append(self.snap(f"{self._focus()['mob'].name} observe.", players=[
                                f"💚 {player['name']} {who} : +{healed} PV "
                                f"(💧 {player['mana']}/{player['mana_max']})" + self._dry_note(player)]))
                            self._void_echo(player)
                            continue

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

                    # Œil de la tempête : la première action frappe tous les
                    # ennemis, et chacun a 50 % de chance d'être étourdi.
                    if (mine.has("storm_eye") and not player["storm_used"]
                            and self._spend(player, "storm_eye")):
                        player["storm_used"] = True
                        for E in self._living_foes():
                            self._strike(player, E, offensive_mult, prefix="🌩️ Œil de la tempête — ",
                                    chained=True, style="storm")
                            if E["hp"] > 0 and not E["is_boss"] and random.random() < 0.50:
                                E["stunned"] = True
                                self._emit("stun", self.ek(E))
                                self.turn_logs.append(self.snap(f"💫 {E['mob'].name} est étourdi par la tempête.",
                                                      focus=E))
                    # Piqué : la première attaque frappe trois fois, à 60 %.
                    elif mine.has("dive") and not player["dived"]:
                        player["dived"] = True
                        for _ in range(3):
                            target = self._player_target()
                            if target is None:
                                break
                            self._strike(player, target, offensive_mult * 0.60, prefix="🦅 Piqué — ", style="dive")
                    else:
                        self._strike(player, self._player_target(), offensive_mult)
                    player["attacks"] += 1
                    # Coup double : 10 % de chance d'attaquer une 2e fois (jamais en chaîne).
                    if (mine.has("double_strike") and self._foes_alive() and random.random() < 0.10
                            and self._spend(player, "double_strike")):
                        self._strike(player, self._player_target(), prefix="⚡ Coup double — ", chained=True,
                                style="double")
                    # Souffle juvénile : toutes les 5 attaques, des flammes
                    # frappent tous les ennemis (30 % de l'ATK, sans défense).
                    if (mine.has("young_breath") and player["attacks"] % 5 == 0 and self._foes_alive()
                            and self._spend(player, "young_breath")):
                        burnt = [f"{E['mob'].name} −{self._hurt_foe(E, max(1, round(stats.attack * 0.30)), player, style='fire')}"
                                 for E in self._living_foes()]
                        self.turn_logs.append(self.snap("🔥 Souffle juvénile de "
                                              f"{player['name']} : " + " · ".join(burnt)))
                    self._void_echo(player)

                    for eff in turn_effects:
                        if eff.kind == SKILL_KIND_SHIELD_SELF:
                            player["shield"] += int(stats.defense * eff.value)
                        elif eff.kind == SKILL_KIND_HEAL_ALLY:
                            heal_amt = int(stats.attack * eff.value)
                            allies = [m for m in self.alive_party
                                      if m["player_id"] != player["player_id"] and m["hp"] > 0]
                            if heal_amt > 0 and allies:
                                target_ally = min(allies, key=lambda m: m["hp"])
                                self._heal(player, target_ally,
                                      heal_amt * mine.heal_power_multiplier)
                        elif eff.kind == SKILL_KIND_SHIELD_TEAM:
                            shield_amt = int(stats.defense * eff.value)
                            if shield_amt > 0:
                                for m in self.alive_party:
                                    if m["hp"] <= 0:
                                        continue
                                    m["shield"] += shield_amt
                                    if m["player_id"] != player["player_id"]:
                                        self.contributions[player["player_id"]].hp_healed += shield_amt

                    if not self._foes_alive():
                        break

            # ── Tour des ennemis ──
            for E in self.foes:
                if E["hp"] <= 0:
                    continue
                if E is self.charm_foe and self._charmed_alive():
                    E["gauge"] = 0  # succube protégée, passive tant que le charmé vit
                self._escalate(E)
                ab = E["ab"]
                foe_actions = 0
                # Garde-fou hard_max aussi ICI : l'escalade multiplie la
                # vitesse du monstre, qui pourrait sinon agir des millions de
                # fois dans un seul tick.
                while (E["gauge"] >= 100 and E["hp"] > 0 and self._party_alive()
                       and not (E is self.charm_foe and self._charmed_alive()) and self.turns < hard_max):
                    self.turns += 1
                    acted = True
                    E["gauge"] -= 100
                    foe_actions += 1
                    E["acted"] = True
                    self._tick_foe_dots(E)
                    if E["hp"] <= 0:
                        break
                    if E["atk_down"]:
                        E["atk_down"] -= 1
                    # Étourdi / gelé par un joueur : perd cette action.
                    if E["stunned"]:
                        E["stunned"] = False
                        E["taunted_by"] = None
                        self._emit("stun", self.ek(E))
                        self.turn_logs.append(self.snap(f"💫 {E['mob'].name} est étourdi et perd son action.",
                                              focus=E))
                        continue

                    # Attaque ultime : une action de charge annoncée, puis le coup.
                    ult = E["ultimate"]
                    if ult:
                        if E["ult_charging"]:
                            E["ult_charging"] = False
                            pool = self._mob_targets()
                            taunter = next((m for m in pool if m["player_id"] == E["taunted_by"]), None)
                            targets = [taunter] if taunter is not None else pool
                            mult = float(ult.get("multiplier", 2)) * (ULTIMATE_SINGLE_MULT if taunter else 1)
                            parts = []
                            for target in targets:
                                shield_before = target["shield"]
                                dmg, crit_u, dodged = self._resolve_mob_hit(
                                    E["mob"], target, self.contributions, self.title_bonuses_by_player,
                                    E["in"], E["family"], extra_multiplier=mult,
                                    attack_override=self._mob_attack_now(E), is_aoe=taunter is None)
                                self._mob_hit_fx(target, E, dmg, crit_u, dodged, "ultimate", shield_before)
                                target.pop("_freeze", None)
                                self._recoil_to_mob(target, E)
                                parts.append(f"{target['name']} esquive" if dodged else
                                             f"{target['name']} −{dmg}" + (" 💀" if target["hp"] <= 0 else "")
                                             + self._tags(target))
                            intercept = f" — 🛡️ {taunter['name']} l'intercepte seul !" if taunter else ""
                            self.turn_logs.append(self.snap(f"💥 ULTIME — {E['mob'].name} déchaîne {ult.get('name', 'son attaque ultime')}"
                                                  f"{intercept} : " + " · ".join(parts), focus=E))
                            E["taunted_by"] = None
                            if not self._party_alive():
                                break
                            continue
                        E["ult_counter"] += 1
                        if E["ult_counter"] % max(2, int(ult.get("every", 6))) == 0:
                            E["ult_charging"] = True
                            self._emit("charge", self.ek(E), style=ult.get("name", ""))
                            self.turn_logs.append(self.snap(f"⚠️ {E['mob'].name} prépare {ult.get('name', 'son attaque ultime')}… "
                                                  + (ult.get("charge") or "Protégez-vous !"), focus=E))
                            continue

                    # Chaman : soin d'urgence (remplace l'attaque de ce tour).
                    if E["chaman_pending"]:
                        E["chaman_pending"] = False
                        before = E["hp"]
                        if anti_heal:
                            E["hp"] += (E["max_hp"] - E["hp"]) // 2
                            self.turn_logs.append(self.snap(f"✨ {E['mob'].name} canalise… le soin est entravé (Anti-soin) !",
                                                  focus=E))
                        else:
                            E["hp"] = E["max_hp"]
                            self._emit("heal", self.ek(E), E["hp"] - before)
                            self.turn_logs.append(self.snap(f"✨ {E['mob'].name} canalise et se soigne à 100% PV !",
                                                  focus=E))
                        continue

                    # Motif d'attaque : zone / mono ; multi-coups ; alternance (liche).
                    aoe = "aoe" in ab
                    single_mult = 1.0
                    if "alternating" in ab:
                        if E["liche_single_next"]:
                            aoe = False
                            single_mult = ab["alternating"].get("single_multiplier", 3)
                        else:
                            aoe = True
                        E["liche_single_next"] = not E["liche_single_next"]
                    hits = int(ab.get("multi_hit", {}).get("hits", 1))
                    atk_now = self._mob_attack_now(E)

                    for _ in range(hits):
                        pool = self._mob_targets()
                        if not pool or E["hp"] <= 0:   # un contrecoup a pu l'achever
                            break
                        targets = pool if aoe else [self._single_target(pool, E)]
                        parts = []
                        for target in targets:
                            shield_before = target["shield"]
                            dmg, mob_crit, dodged = self._resolve_mob_hit(
                                E["mob"], target, self.contributions, self.title_bonuses_by_player,
                                E["in"], E["family"],
                                extra_multiplier=single_mult, attack_override=atk_now,
                                is_aoe=aoe)
                            self._mob_hit_fx(target, E, dmg, mob_crit, dodged, "aoe" if aoe else "melee",
                                        shield_before)
                            # Vol de vie (gargouille) — divisé par deux par Anti-soin
                            if not dodged and dmg > 0 and "lifesteal" in ab and E["hp"] > 0:
                                heal = round(dmg * ab["lifesteal"].get("pct", 0) / 100)
                                if anti_heal:
                                    heal //= 2
                                if heal > 0:
                                    before = E["hp"]
                                    E["hp"] = min(E["max_hp"], E["hp"] + heal)
                                    self._emit("heal", self.ek(E), E["hp"] - before)
                            # Contrecoup (Épines compris) : la DEF en trop frappe le monstre.
                            self._recoil_to_mob(target, E)
                            # Riposte : 10 % de chance de contre-attaquer (jamais en chaîne).
                            if (not dodged and target["hp"] > 0 and E["hp"] > 0
                                    and self.P(target).has("counter_attack") and random.random() < 0.10
                                    and self._spend(target, "counter_attack")):
                                self._strike(target, E, prefix="↩️ Riposte — ", chained=True, style="counter")
                            # Morsure du givre : l'attaquant (hors boss) perd sa prochaine action.
                            frozen_now = False
                            if (target.pop("_freeze", False) and E["hp"] > 0 and not E["is_boss"]
                                    and not E["stunned"] and self._spend(target, "frost_bite")):
                                E["stunned"] = True
                                frozen_now = True
                                self._emit("stun", self.ek(E), style="freeze")
                            # Étourdissement (gobelin géant / banshee) — non cumulable
                            stunned_now = False
                            if not dodged and "stun" in ab and not target["stunned"]:
                                if random.random() < ab["stun"].get("chance", 0) / 100:
                                    target["stunned"] = True
                                    stunned_now = True
                                    self._emit("stun", self.pk(target), source=self.ek(E))
                            # Ralentissement (momie, mono-cible) — +1 stack de durée
                            if not dodged and not aoe and "slow" in ab:
                                target["slow"] += 1
                            # Saignement (ogre) : +1 stack (10% des dégâts / tour, 3 tours, max 3).
                            if not dodged and dmg > 0 and "bleed" in ab:
                                bc = ab["bleed"]
                                if len(target["bleeds"]) < bc.get("max_stacks", 3):
                                    target["bleeds"].append(
                                        {"dmg": max(1, round(dmg * bc.get("pct", 10) / 100)),
                                         "turns": bc.get("turns", 3)})
                            # Poison : (r)empoisonne la cible — non cumulable, la
                            # durée repart à zéro.
                            if not dodged and dmg > 0 and "poison" in ab:
                                pc = ab["poison"]
                                target["poison"] = {
                                    "dmg": max(1, round(target["max_hp"] * pc.get("pct_max_hp", 2) / 100)),
                                    "turns": pc.get("turns", 4),
                                }
                            # Brise-armure : la DEF de la cible baisse pour le combat.
                            if not dodged and dmg > 0 and "armor_break" in ab:
                                ac = ab["armor_break"]
                                target["armor_break"] = min(
                                    ac.get("max_pct", 30), target["armor_break"] + ac.get("pct", 10))
                            # Kill → recharge du bouclier (gobelin supérieur)
                            if target["hp"] <= 0 and ab.get("shield", {}).get("reset_on_kill"):
                                E["shield"] = E["max_hp"]
                            if dodged:
                                parts.append(f"{target['name']} esquive")
                            else:
                                tag = " CRIT" if mob_crit else ""
                                tag += " 💫" if stunned_now else ""
                                tag += " 🐌" if (not aoe and "slow" in ab) else ""
                                tag += " 🩸" if "bleed" in ab else ""
                                tag += " ☠️" if "poison" in ab else ""
                                tag += f" 🔨−{target['armor_break']}%" if "armor_break" in ab else ""
                                tag += " 💀" if target["hp"] <= 0 else ""
                                tag += f" ❄️ {E['mob'].name} gelé" if frozen_now else ""
                                tag += self._tags(target)
                                parts.append(f"{target['name']} −{dmg}{tag}")
                        verb = "déchaîne une frappe de zone" if aoe else "frappe"
                        heal_tag = " (vol de vie)" if "lifesteal" in ab else ""
                        self.turn_logs.append(self.snap(f"{E['mob'].name} {verb}{heal_tag} : " + " · ".join(parts),
                                              focus=E))
                        if not self._party_alive():
                            break

                    # Réaction en chaîne (gobelin ballon) : chaque salve peut se répliquer.
                    if "chain_replicate" in ab and self._party_alive() and E["hp"] > 0:
                        chance = ab["chain_replicate"].get("chance", 20) / 100
                        rep = 0
                        while self._party_alive() and random.random() < chance and rep < 15:
                            rep += 1
                            pool = self._mob_targets()
                            if not pool:
                                break
                            rtargets = pool if aoe else [self._single_target(pool, E)]
                            parts = []
                            for target in rtargets:
                                shield_before = target["shield"]
                                dmg, mob_crit, dodged = self._resolve_mob_hit(
                                    E["mob"], target, self.contributions, self.title_bonuses_by_player,
                                    E["in"], E["family"],
                                    extra_multiplier=single_mult, attack_override=atk_now,
                                    is_aoe=aoe)
                                self._mob_hit_fx(target, E, dmg, mob_crit, dodged, "explosion", shield_before)
                                target.pop("_freeze", None)
                                self._recoil_to_mob(target, E)
                                parts.append(f"{target['name']} esquive" if dodged
                                             else f"{target['name']} −{dmg}"
                                             + (" 💀" if target["hp"] <= 0 else "")
                                             + self._tags(target))
                            self.turns += 1
                            self.turn_logs.append(self.snap(f"💥 Réaction en chaîne (réplique {rep}) : "
                                                  + " · ".join(parts), focus=E))

                    # La provocation ne vaut que pour la PROCHAINE attaque.
                    E["taunted_by"] = None
                    if not self._party_alive():
                        break

                # Effets « à chaque tour de l'ennemi » : un passage par action
                # jouée pendant ce tick (pas un par tick).
                for _ in range(foe_actions):
                    E["turn_count"] += 1
                    if E["hp"] <= 0 or not self._party_alive():
                        break
                    # Invocations (adds) : une de plus tous les `summon_turn_interval`
                    # tours, chacune frappe un joueur au hasard.
                    if E["adds_attack"] > 0 and E["adds_interval"] > 0 and E["adds_max"] > 0:
                        if E["turn_count"] % E["adds_interval"] == 0 and E["active_adds"] < E["adds_max"]:
                            E["active_adds"] += 1
                        for _ in range(E["active_adds"]):
                            alive = [p for p in self.alive_party if p["hp"] > 0]
                            if not alive:
                                break
                            victim = random.choice(alive)
                            # Même formule ; pas de contrecoup : une invocation
                            # n'a pas de PV à elle.
                            add_dmg, _ = resolve_hit(E["adds_attack"], victim["stats"].defense)
                            taken = self._apply_player_damage(victim, add_dmg)
                            self._emit("hit", self.pk(victim), taken, source=self.ek(E), style="summon")
                            self.contributions[victim["player_id"]].damage_tanked += E["adds_attack"]
                    # Régénération (monstres des zones hautes) : % des PV max par action.
                    if "regen" in ab and E["hp"] < E["max_hp"]:
                        heal = round(E["max_hp"] * ab["regen"].get("pct", 3) / 100)
                        heal = heal // 2 if anti_heal else heal
                        before = E["hp"]
                        E["hp"] = min(E["max_hp"], E["hp"] + heal)
                        self._emit("heal", self.ek(E), E["hp"] - before)
                    # Auto-soin du boss.
                    if E["heal_per_turn"] > 0:
                        heal = E["heal_per_turn"] // 2 if anti_heal else E["heal_per_turn"]
                        before = E["hp"]
                        E["hp"] = min(E["max_hp"], E["hp"] + heal)
                        self._emit("heal", self.ek(E), E["hp"] - before)
                if not self._party_alive():
                    break

            if not acted:
                continue

        for member in self.alive_party:
            contribution = self.contributions[member["player_id"]]
            contribution.final_hp = member["hp"]
            contribution.final_mana = member["mana"]
            contribution.mana_max = member["mana_max"]
            contribution.survived = member["hp"] > 0

        surviving_players = [player["name"] for player in self.alive_party if player["hp"] > 0]
        defeated_players = [player["name"] for player in self.alive_party if player["hp"] <= 0]
        victory = not self._foes_alive()
        names = [E["base"].name for E in self.foes]
        mob_name = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " et " + names[-1]

        return PartyBattleResult(
            victory=victory,
            turns=self.turns,
            mob_name=mob_name,
            mob_image_name=self.foes[0]["base"].image_name,
            mob_remaining_hp=sum(max(0, E["hp"]) for E in self.foes),
            surviving_players=surviving_players,
            defeated_players=defeated_players,
            xp_gained=sum(E["base"].xp_reward for E in self.foes) if victory else 0,
            gold_gained=sum(E["base"].gold_reward for E in self.foes) if victory else 0,
            summary=(
                f"Le groupe a vaincu {mob_name} en {self.turns} action(s)."
                if victory
                else f"Le groupe a été vaincu par {mob_name}."
            ),
            turn_logs=self.turn_logs,
            contributions=list(self.contributions.values()),
            enemies=[
                {"code": E["base"].code, "name": E["base"].name, "max_hp": E["max_hp"],
                 "remaining_hp": max(0, E["hp"]), "defeated": E["hp"] <= 0}
                for E in self.foes
            ],
        )


