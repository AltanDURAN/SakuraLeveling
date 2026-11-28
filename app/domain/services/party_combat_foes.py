"""Les ENNEMIS d'un combat de groupe : état, phases, gardes, escalade, mort,
dégâts reçus et effets sur la durée.

Méthodes de `PartyCombatService` (mixin), sorties de
`party_combat_service.py` le 28/11/2026 (audit) : texte inchangé. L'état
du combat en cours vit sur l'instance (une par combat)."""

from dataclasses import replace



from app.domain.services.party_combat_rules import ESCALATION_EVERY, ESCALATION_START, ESCALATION_STEP, EnemySetup, escalation_multiplier


class FoesMixin:
    # ── Ennemis ──
    def _foe(self, i: int, setup: EnemySetup) -> dict:
        mob = setup.mob
        ab = dict(setup.abilities or {})
        # Un MONSTRE peut aussi invoquer ou renvoyer des dégâts (capacités
        # `summon` / `reflect`, zones C → S) : même mécanique que les boss.
        adds = setup.adds
        if "summon" in ab and not adds:
            sm = ab["summon"]
            adds = {
                "attack": max(1, round(mob.attack * sm.get("atk_pct", 30) / 100)),
                "summon_turn_interval": sm.get("every", 3),
                "max_active": sm.get("max", 2),
            }
        reflect = setup.reflect_pct
        if "reflect" in ab:
            reflect = max(reflect, int(ab["reflect"].get("pct", 0)))
        adds = adds or {}
        return {
            "i": i, "base": mob, "mob": mob, "ab": ab, "family": mob.family or "",
            "hp": mob.current_hp, "max_hp": mob.max_hp, "gauge": 0,
            # Capacités du monstre
            "bonus_atk": 0.0, "bonus_def": 0.0,          # absorption (slime)
            "shield": mob.max_hp if "shield" in ab else 0,
            "revived": False,
            "chaman_pending": False, "chaman_done": False,
            "liche_single_next": False,                   # commence par une frappe de zone
            "ghost_dodged": set(),                        # fantôme : 1re attaque esquivée
            # Tours JOUÉS par l'ennemi : base de l'escalade, du soin et des
            # invocations. La boucle avance par TICKS de jauge (un
            # combattant agit tous les 100/vitesse ticks) : appliquer ces
            # effets à chaque tick les multipliait par ~10-20.
            "turn_count": 0, "escalation": 0, "acted": False,
            "adds_attack": int(adds.get("attack", 0)),
            "adds_interval": int(adds.get("summon_turn_interval", 0)),
            "adds_max": int(adds.get("max_active", 0)),
            "active_adds": 0,
            "reflect_pct": reflect, "heal_per_turn": setup.heal_per_turn,
            "immunity": setup.immunity_threshold, "is_boss": setup.is_boss,
            "out": setup.elemental_out or {}, "in": setup.elemental_in or {},
            "infusion": setup.infusion or {},
            # Effets posés par les joueurs (passifs d'équipement)
            "taunted_by": None,     # provocation : SA prochaine attaque
            "stunned": False,       # étourdi / gelé : perd sa prochaine action
            "armor_break": 0,       # % de DEF brisée (Coup de patte, max 15)
            "slow_pct": 0,          # % de vitesse en moins (Étreinte astrale, max 25)
            "poison": None,         # Sève vénéneuse : {dmg, turns, by}
            "burns": [],            # Braise persistante : [{dmg, turns, by}]
            "bleeds": [],           # Valse sanglante : [{dmg, turns, by}]
            "atk_down": 0,          # Braise persistante : actions à −20 % d'ATK
            "down": False,          # sa mort a été traitée
            # World boss : phases, ultime, gardes
            "decisive": setup.decisive, "guard": setup.guard,
            "guarded_pct": setup.guarded_reduction_pct,
            "phases": sorted((dict(ph) for ph in setup.phases or []),
                             key=lambda ph: -float(ph.get("below_pct", 0))),
            "phase_atk_pct": 0.0, "phase_name": "",
            "ultimate": setup.ultimate, "ult_counter": 0, "ult_charging": False,
        }

    def _living_foes(self) -> list:
        return [E for E in self.foes if E["hp"] > 0]

    def _foes_alive(self) -> bool:
        """Le combat continue tant qu'un ennemi décisif (le boss) ou, à
        défaut, un ennemi quelconque est debout."""
        return any(E["hp"] > 0 for E in (self.decisive_foes or self.foes))

    def _guards_up(self) -> bool:
        return any(E["guard"] and E["hp"] > 0 for E in self.foes)

    def _guarded(self, E, damage: int) -> int:
        """Dégâts sur un boss protégé par ses gardes."""
        if E["guarded_pct"] > 0 and damage > 0 and self._guards_up():
            return max(1, round(damage * (1 - E["guarded_pct"] / 100)))
        return damage

    def _activate_phase(self, E, phase: dict, announce: bool = True) -> None:
        """Sous un seuil de PV, l'ennemi change de comportement."""
        phase["active"] = True
        E["phase_name"] = phase.get("name", "")
        E["phase_atk_pct"] += float(phase.get("attack_pct", 0))
        for key, cfg in (phase.get("abilities") or {}).items():
            if key == "summon":
                E["adds_attack"] = max(1, round(E["base"].attack * cfg.get("atk_pct", 30) / 100))
                E["adds_interval"] = int(cfg.get("every", 3))
                E["adds_max"] = int(cfg.get("max", 2))
            else:
                E["ab"][key] = cfg
        if announce:
            self._emit("phase", self.ek(E), style=E["phase_name"])
            self.turn_logs.append(self.snap(f"⚡ {E['mob'].name} entre en phase « {E['phase_name']} »"
                                  + (f" : {phase['text']}" if phase.get("text") else ""), focus=E))

    def _neighbours(self, E) -> list:
        """Ennemis voisins de E dans la formation (dégâts de zone)."""
        living = self._living_foes()
        if E not in living:
            return []
        k = living.index(E)
        return [F for F in (living[k - 1] if k > 0 else None,
                            living[k + 1] if k + 1 < len(living) else None) if F is not None]

    def _enrage_pct(self, E) -> int:
        tiers = E["ab"].get("enrage", {}).get("tiers", [])
        if not tiers or not E["max_hp"]:
            return 0
        ratio = E["hp"] / E["max_hp"] * 100
        return max((b for t, b in tiers if ratio <= t), default=0)

    def _mob_attack_now(self, E) -> int:
        a = float(E["mob"].attack) + E["bonus_atk"]
        if E["revived"]:
            a *= 1 + E["ab"].get("revive", {}).get("atk_pct", 0) / 100
        a *= 1 + self._enrage_pct(E) / 100
        if E["atk_down"]:   # Braise persistante (non cumulable)
            a *= 0.80
        if E["phase_atk_pct"]:
            a *= 1 + E["phase_atk_pct"] / 100
        return max(1, int(round(a)))

    def _mob_defense_now(self, E) -> int:
        d = float(E["mob"].defense) + E["bonus_def"]
        if E["revived"]:
            d *= 1 + E["ab"].get("revive", {}).get("def_pct", 0) / 100
        # La furie ne touche PAS la défense : en combat soustractif, une DEF
        # qui approche l'ATK des joueurs met chaque coup au plancher de 1
        # (l'Archidémon était imbattable même à 4, audit du 24/10/2026).
        if E["armor_break"]:   # Coup de patte brisant
            d *= 1 - E["armor_break"] / 100
        return int(round(d))

    def _escalate(self, E) -> None:
        """Applique le palier d'escalade atteint (cf. ESCALATION_EVERY)."""
        level = max(0, E["turn_count"] - ESCALATION_START) // ESCALATION_EVERY
        if level <= E["escalation"] or E["hp"] <= 0:
            return
        E["escalation"] = level
        mult = escalation_multiplier(E["turn_count"])
        base = E["base"]
        E["mob"] = replace(
            base,
            attack=max(1, round(base.attack * mult)),
            defense=round(base.defense * mult),
            speed=max(1, round(base.speed * mult)),
            crit_chance=min(100, base.crit_chance * mult),
            crit_damage=max(100, base.crit_damage * mult),
            current_hp=E["hp"],
        )
        self._emit("enrage", self.ek(E))
        self.turn_logs.append(self.snap(
            f"🔥 Le combat s'éternise : {E['mob'].name} se renforce "
            f"(+{round(ESCALATION_STEP * level * 100)} %, ×{mult:.2f} au total)", focus=E))

    def _check_mob_thresholds(self, E) -> None:
        """Seuils de PV de l'ennemi, quelle que soit la source des dégâts
        (coup, contrecoup, poison) : soin d'urgence du chaman,
        résurrection — puis sa mort."""
        ab = E["ab"]
        # Chaman : 1ʳᵉ fois sous 50% PV → soin d'urgence au prochain tour.
        if ("heal_once_below" in ab and not E["chaman_done"] and E["hp"] > 0
                and E["hp"] <= E["max_hp"] * ab["heal_once_below"].get("hp_pct", 50) / 100):
            E["chaman_pending"] = True
            E["chaman_done"] = True
        # Résurrection (ange déchu) : 1ʳᵉ mort → revient à 100% PV.
        if E["hp"] <= 0 and "revive" in ab and not E["revived"]:
            E["revived"] = True
            E["hp"] = E["max_hp"]
            self._emit("revive", self.ek(E))
            self.turn_logs.append(self.snap(
                f"👼 {E['mob'].name} renaît à 100% PV, transcendé "
                f"(+{ab['revive'].get('atk_pct', 0)}% d'attaque) !", focus=E))
        if E["hp"] <= 0 and not E["down"]:
            self._foe_down(E)
        # Phases : chaque seuil de PV franchi change son comportement.
        if E["hp"] > 0 and E["phases"]:
            ratio = E["hp"] / max(1, E["max_hp"]) * 100
            for phase in E["phases"]:
                if not phase.get("active") and ratio <= float(phase.get("below_pct", 0)):
                    self._activate_phase(E, phase)

    def _foe_down(self, E) -> None:
        """Mort d'un ennemi : explosion (kamikaze), joueurs engloutis
        relâchés, charme levé, Festin de chair."""
        E["down"] = True
        self._emit("ko", self.ek(E))
        cfg = E["ab"].get("death_explosion")
        victims = [p for p in self.alive_party if p["hp"] > 0]
        if cfg and victims:
            mult = int(cfg.get("attack_multiplier", 3))
            parts = []
            for target in victims:
                shield_before = target["shield"]
                dmg, crit, dodged = self._resolve_mob_hit(
                    E["mob"], target, self.contributions, self.title_bonuses_by_player,
                    E["in"], E["family"], extra_multiplier=mult, is_aoe=True)
                self._mob_hit_fx(target, E, dmg, crit, dodged, "explosion", shield_before)
                target.pop("_recoil", None)  # le monstre est déjà mort
                target.pop("_mirror", None)
                target.pop("_freeze", None)
                if dodged:
                    parts.append(f"{target['name']} esquive")
                else:
                    tag = " CRIT" if crit else ""
                    dead = " 💀" if target["hp"] <= 0 else ""
                    parts.append(f"{target['name']} −{dmg}{tag}{dead}")
            self.turn_logs.append(self.snap(f"💥 {E['mob'].name} explose à sa mort ! " + " · ".join(parts), focus=E))
        for p in self.alive_party:
            if p["absorbed_by"] == E["i"] and p["hp"] > 0:
                p["absorbed"] = False
                p["absorbed_by"] = None
        if self.charm_foe is E and self.charmed_id is not None:
            freed = self._charmed_member()
            if freed is not None:
                freed["charmed"] = False
            self.charmed_id = None
        # Festin de chair : chaque ennemi vaincu rend 25 % des PV max.
        feast = []
        for m in self.alive_party:
            if (self.P(m).has("flesh_feast") and m["hp"] > 0 and not m["absorbed"]
                    and m["hp"] < m["max_hp"] and self._spend(m, "flesh_feast")):
                healed = self._heal(m, m, m["max_hp"] * 0.25, allow_buff=False)
                if healed:
                    feast.append(f"{m['name']} +{healed}")
        if feast:
            self.turn_logs.append(self.snap("🍖 Festin de chair : " + " · ".join(feast), focus=E))

    def _hurt_foe(self, E, amount: int, member, *, through_shield: bool = True,
                  kind: str = "hit", style: str = "magic") -> int:
        """Dégâts DIRECTS à un ennemi (zone, souffle, écho, poison…) : ni
        défense ni esquive ; le bouclier du monstre absorbe d'abord (sauf
        poisons), l'immunité d'un boss ignore les coups trop faibles.
        Comptés dans les dégâts infligés de `member`."""
        if E is None or E["hp"] <= 0 or amount <= 0:
            return 0
        amount = self._guarded(E, amount)
        if E["immunity"] > 0 and amount < E["immunity"]:
            self._emit("immune", self.ek(E))
            return 0
        if through_shield and E["shield"] > 0:
            absorbed = min(E["shield"], amount)
            E["shield"] -= absorbed
            amount -= absorbed
        dealt = min(E["hp"], amount)
        E["hp"] -= dealt
        if member is not None:
            self.contributions[member["player_id"]].damage_dealt += dealt
        self._emit(kind, self.ek(E), dealt, source=self.pk(member) if member is not None else None, style=style)
        self._check_mob_thresholds(E)
        return dealt

    def _recoil_to_mob(self, defender, E) -> None:
        """Contrecoup : la défense du joueur en trop renvoie des dégâts à
        l'ennemi (cf. damage_formula). Ni action, ni effet déclenché ; le
        bouclier du monstre ne l'arrête pas. Compté dans les dégâts
        infligés. Miroir d'éclipse : 15 % des dégâts reçus, de même."""
        recoil = defender.pop("_recoil", 0)
        mirror = defender.pop("_mirror", 0)
        for amount, key in ((recoil, "_recoil_dealt"), (mirror, "_mirror_dealt")):
            if amount <= 0 or E["hp"] <= 0:
                continue
            dealt = min(E["hp"], amount)
            E["hp"] -= dealt
            self.contributions[defender["player_id"]].damage_dealt += dealt
            defender[key] = dealt
            self._emit("recoil" if key == "_recoil_dealt" else "mirror", self.ek(E), dealt,
                       source=self.pk(defender))
            self._check_mob_thresholds(E)

    def _tick_foe_dots(self, E) -> None:
        """Poison, brûlures et saignements posés par les joueurs : une fois
        par action de l'ennemi (même règle que pour les joueurs). Ils
        ignorent son bouclier et sa défense."""
        lines = []
        pz = E["poison"]
        if pz:
            dealt = self._hurt_foe(E, pz["dmg"], self._member(pz["by"]), through_shield=False,
                              kind="dot", style="poison")
            lines.append(f"🐍 Sève : −{dealt}")
            pz["turns"] -= 1
            if pz["turns"] <= 0:
                E["poison"] = None
        for key, label in (("burns", "🔥 Brûlure"), ("bleeds", "🩸 Saignement")):
            if not E[key] or E["hp"] <= 0:
                continue
            total = 0
            for dot in E[key]:
                total += self._hurt_foe(E, dot["dmg"], self._member(dot["by"]), through_shield=False,
                                   kind="dot", style="burn" if key == "burns" else "bleed")
                dot["turns"] -= 1
            E[key] = [d for d in E[key] if d["turns"] > 0]
            lines.append(f"{label} : −{total}")
        if lines:
            self.turn_logs.append(self.snap(f"{E['mob'].name} — " + " · ".join(lines)
                                  + (" 💀" if E["hp"] <= 0 else ""), focus=E))

    @staticmethod
    def _enemy_state(E) -> dict:
        mob = E["mob"]
        return {
            "code": E["base"].code,
            "name": mob.name,
            "image_name": mob.image_name,
            "element": getattr(E["base"], "element", "") or "",
            "current_hp": E["hp"],
            "max_hp": E["max_hp"],
            "shield": E["shield"],
            "attack": mob.attack,
            "defense": mob.defense,
            "speed": mob.speed,
            "crit_chance": mob.crit_chance,
            "crit_damage": mob.crit_damage,
            "dodge": mob.dodge,
            "hp_regeneration": mob.hp_regeneration,
        }
