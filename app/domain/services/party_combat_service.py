import random
from dataclasses import dataclass, field, replace

from app.domain.entities.element_skill import (
    SKILL_KIND_DAMAGE,
    SKILL_KIND_HEAL_ALLY,
    SKILL_KIND_SHIELD_SELF,
    SKILL_KIND_SHIELD_TEAM,
)
from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.combat_passives import (
    BASE_HEAL_PCT,
    HEAL_BELOW_PCT,
    MANA_ABILITY_NAMES,
    MANA_COSTS,
    NO_PASSIVES,
    CombatPassives,
    normalize_tactic,
)
from app.domain.services.damage_formula import resolve_hit, thorns_recoil
from app.domain.services.power_score_service import PowerScoreService
from app.domain.services.skill_effect_service import SkillEffectService
from app.domain.services.title_bonus_service import TitleBonuses
from app.domain.value_objects.party_battle_result import PartyBattleResult
from app.domain.value_objects.party_battle_turn_log import PartyBattleTurnLog
from app.domain.value_objects.player_contribution import PlayerContribution
from app.domain.value_objects.stats import Stats


#: Escalade : à partir de la 30e action DU MONSTRE, puis toutes les 5, il se
#: renforce de +10 % × palier, PAR-DESSUS les paliers précédents (30e : ×1,1 ;
#: 35e : ×1,1×1,2 ; 40e : ×1,1×1,2×1,3…). Comptée en actions du MONSTRE
#: (25/10/2026) : comptée en actions de tout le monde, elle arrivait 3 fois
#: plus tôt à 3 joueurs et favorisait ceux qui tuent vite (les DPS). En solo,
#: c'est le même moment qu'avant (~50 actions au total). Seules ses stats
#: OFFENSIVES montent (attaque, défense, vitesse, critiques) : augmenter ses
#: PV ou son esquive rallongerait le combat, l'inverse du but — et les PV d'un
#: world boss sont conservés d'un jour à l'autre. Contre un GROUPE d'ennemis,
#: chacun compte ses propres actions.
ESCALATION_START = 25    # 1er palier à la 30e action du monstre (25 + 5)
ESCALATION_EVERY = 5
ESCALATION_STEP = 0.10

#: Garde-fou absolu du nombre d'actions, en dernier recours si l'escalade ne
#: suffit pas (ex. Soigneurs qui soignent tout). Atteint ⇒ monstre non vaincu.
#: Multiplié par le nombre d'ennemis (chacun agit).
HARD_MAX_TURNS = 500

#: Aggro : un monstre vise de préférence le joueur le plus SOLIDE (PV max +
#: DEF × 25, la robustesse du power score), poids à la puissance 3 — un tank
#: deux fois plus robuste qu'un DPS prend 8 fois plus de coups que lui. Avant
#: (25/10/2026), la cible était tirée au hasard : le tank ne protégeait
#: personne. La provocation reste prioritaire.
THREAT_DEF_WEIGHT = 25
THREAT_EXPONENT = 3

#: Sève vénéneuse : le poison d'un tour vaut 1 % des PV max de l'ennemi,
#: plafonné à 25 % de l'ATK du porteur — sans plafond, contre un boss ou une
#: élite à ×20 PV, il frappait plus fort que le porteur lui-même.
ROOT_VENOM_PCT = 1
ROOT_VENOM_ATK_CAP_PCT = 25


def escalation_multiplier(mob_actions: int) -> float:
    """Multiplicateur cumulé des stats du monstre après `mob_actions` actions
    du monstre."""
    mult = 1.0
    for level in range(1, max(0, mob_actions - ESCALATION_START) // ESCALATION_EVERY + 1):
        mult *= 1 + ESCALATION_STEP * level
    return mult


@dataclass
class EnemySetup:
    """Un ennemi d'un combat de groupe (`fight_party_vs_mobs`).

    `elemental_out` / `elemental_in` : multiplicateurs élémentaires PAR
    JOUEUR contre cet ennemi (ses dégâts infligés / reçus). Les modificateurs
    de boss (immunité, soin, renvoi, invocations) sont propres à l'ennemi."""

    mob: MobDefinition
    abilities: dict = field(default_factory=dict)
    elemental_out: dict[int, float] = field(default_factory=dict)
    elemental_in: dict[int, float] = field(default_factory=dict)
    is_boss: bool = False
    #: Élément d'attaque infusé de chaque joueur contre cet ennemi (affichage).
    infusion: dict[int, str] = field(default_factory=dict)
    immunity_threshold: int = 0
    heal_per_turn: int = 0
    reflect_pct: int = 0
    adds: dict | None = None


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
        title_bonuses_by_player = title_bonuses_by_player or {}
        skill_loadouts_by_player = skill_loadouts_by_player or {}
        passives_by_player = passives_by_player or {}
        tactics_by_player = tactics_by_player or {}
        self._passives = passives_by_player
        self._mana_costs = MANA_COSTS if mana_costs is None else mana_costs
        # Événements de l'action en cours (chiffres et effets dessinés sur la
        # scène) : vidés dans chaque instantané du journal. Pur enregistrement,
        # aucun tirage — le combat est identique avec ou sans affichage.
        self._events: list[dict] = []
        _skill_svc = SkillEffectService()
        hard_max = HARD_MAX_TURNS * max(1, len(enemies))

        def P(member) -> CombatPassives:
            return passives_by_player.get(member["player_id"], NO_PASSIVES)

        def pk(member) -> str:
            return f"p{member['player_id']}"

        def ek(E) -> str:
            return f"e{E['i']}"
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

        self._party = alive_party
        # Effets sur l'ennemi : UN exemplaire actif, quel que soit le nombre
        # de porteurs (dix joueurs à −5 % d'ATK, ça reste −5 %).
        anti_heal = any(P(m).has("anti_heal") for m in alive_party)
        self._mob_atk_mult = 0.95 if any(P(m).has("weakening_cry") for m in alive_party) else 1.0
        contributions: dict[int, PlayerContribution] = {
            member["player_id"]: PlayerContribution(
                player_id=member["player_id"],
                user_id=member["user_id"],
                name=member["name"],
                max_hp=member["max_hp"],
                final_hp=member["hp"],
                mana_max=member["mana_max"],
            )
            for member in alive_party
        }
        self._contribs = contributions

        # ── Ennemis ──
        def _foe(i: int, setup: EnemySetup) -> dict:
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
            }

        foes = [_foe(i, setup) for i, setup in enumerate(enemies)]
        self._foes = foes

        def _living_foes() -> list:
            return [E for E in foes if E["hp"] > 0]

        def _foes_alive() -> bool:
            return any(E["hp"] > 0 for E in foes)

        def _player_target():
            """L'ennemi le plus ABÎMÉ (part de PV la plus basse) : on se concentre."""
            living = _living_foes()
            if not living:
                return None
            return min(living, key=lambda E: (E["hp"] / max(1, E["max_hp"]), E["i"]))

        def _neighbours(E) -> list:
            """Ennemis voisins de E dans la formation (dégâts de zone)."""
            living = _living_foes()
            if E not in living:
                return []
            k = living.index(E)
            return [F for F in (living[k - 1] if k > 0 else None,
                                living[k + 1] if k + 1 < len(living) else None) if F is not None]

        # ── État du charme (succube) ──
        charmed_id: int | None = None
        charm_foe = None
        _power = PowerScoreService()

        def _charmed_member():
            return next((p for p in alive_party if p["player_id"] == charmed_id), None)

        def _charmed_alive() -> bool:
            m = _charmed_member()
            return m is not None and m["hp"] > 0

        escort = frozenset(escort_ids or ())

        def _party_alive() -> bool:
            if escort and any(p["hp"] <= 0 for p in alive_party if p["player_id"] in escort):
                return False
            return any(p["hp"] > 0 and p["player_id"] != charmed_id and not p["absorbed"]
                       for p in alive_party)

        def _mob_targets() -> list:
            return [p for p in alive_party
                    if p["hp"] > 0 and p["player_id"] != charmed_id and not p["absorbed"]
                    and (not escort or p["player_id"] in escort)]

        def _enrage_pct(E) -> int:
            tiers = E["ab"].get("enrage", {}).get("tiers", [])
            if not tiers or not E["max_hp"]:
                return 0
            ratio = E["hp"] / E["max_hp"] * 100
            return max((b for t, b in tiers if ratio <= t), default=0)

        def _mob_attack_now(E) -> int:
            a = float(E["mob"].attack) + E["bonus_atk"]
            if E["revived"]:
                a *= 1 + E["ab"].get("revive", {}).get("atk_pct", 0) / 100
            a *= 1 + _enrage_pct(E) / 100
            if E["atk_down"]:   # Braise persistante (non cumulable)
                a *= 0.80
            return max(1, int(round(a)))

        def _mob_defense_now(E) -> int:
            d = float(E["mob"].defense) + E["bonus_def"]
            if E["revived"]:
                d *= 1 + E["ab"].get("revive", {}).get("def_pct", 0) / 100
            # La furie ne touche PAS la défense : en combat soustractif, une DEF
            # qui approche l'ATK des joueurs met chaque coup au plancher de 1
            # (l'Archidémon était imbattable même à 4, audit du 24/10/2026).
            if E["armor_break"]:   # Coup de patte brisant
                d *= 1 - E["armor_break"] / 100
            return int(round(d))

        def _escalate(E) -> None:
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
            self._emit("enrage", ek(E))
            turn_logs.append(snap(
                f"🔥 Le combat s'éternise : {E['mob'].name} se renforce "
                f"(+{round(ESCALATION_STEP * level * 100)} %, ×{mult:.2f} au total)", focus=E))

        def snap(action, players=None, focus=None):
            return self._snapshot(turns, players or [], action, alive_party, foes,
                                  focus if focus is not None else _focus(), self._take_events())

        def _focus():
            return _player_target() or foes[-1]

        # ── Passifs : soins, provocation (cf. combat_passives) ──
        def _taunters() -> set[int]:
            return {E["taunted_by"] for E in foes if E["hp"] > 0 and E["taunted_by"] is not None}

        def _provoke(member) -> None:
            """Provocation : la PROCHAINE attaque de chaque ennemi le vise."""
            for E in _living_foes():
                E["taunted_by"] = member["player_id"]

        def _buff(member, pct: float) -> None:
            if member["buffed"] or pct <= 0:
                return
            st = member["stats"]
            member["stats"] = replace(
                st,
                attack=max(1, round(st.attack * (1 + pct / 100))),
                defense=max(0, round(st.defense * (1 + pct / 100))),
            )
            member["buffed"] = True

        def _heal(healer, target, amount: float, allow_buff: bool = True) -> int:
            """Soigne `target` : soins reçus (Paladin), Buff (cible + soigneur).
            Seuls les soins donnés aux ALLIÉS comptent dans la contribution.
            Mains guérisseuses : soins donnés +10 %, et 10 % des soins donnés à
            un allié frappent l'ennemi. Pas de l'ombre : prochain soin +10 %.
            Ramure bienveillante : +15 % de soins reçus pour tout le groupe
            (une seule aura)."""
            if amount <= 0 or target["hp"] <= 0:
                return 0
            if P(healer).has("healing_hands"):
                amount *= 1.10
            if allow_buff and healer["shadow"]:
                amount *= 1.10
                healer["shadow"] = False
            amount *= 1 + P(target).heal_received_pct / 100
            if any(P(m).has("kind_antlers") and m["hp"] > 0 for m in alive_party):
                amount *= 1.15
            before = target["hp"]
            target["hp"] = min(target["max_hp"], target["hp"] + int(round(amount)))
            healed = target["hp"] - before
            if healed > 0:
                self._emit("heal", pk(target), healed, source=pk(healer))
            if healer["player_id"] != target["player_id"]:
                contributions[healer["player_id"]].hp_healed += healed
                if P(healer).has("healing_hands") and healed > 0 and _foes_alive():
                    _hurt_foe(_player_target(), max(1, round(healed * 0.10)), healer, style="holy")
            if allow_buff and P(healer).heal_buff_pct > 0:
                _buff(target, P(healer).heal_buff_pct)
                _buff(healer, P(healer).heal_buff_pct)
            return healed

        def _heal_target(healer):
            """Cible du sort de soin selon la tactique (figée pour le combat),
            parmi les alliés sous `HEAL_BELOW_PCT` % de leurs PV."""
            team = [m for m in alive_party
                    if m["hp"] > 0 and not m["absorbed"] and m["player_id"] != charmed_id]
            injured = [m for m in team if m["hp"] < m["max_hp"] * HEAL_BELOW_PCT / 100]
            if not injured:
                return None
            tactic = normalize_tactic(tactics_by_player.get(healer["player_id"]))
            if tactic == "egoiste":
                if healer in injured:
                    return healer
                return min(injured, key=lambda m: m["hp"] / max(1, m["max_hp"]))
            metric = "damage_tanked" if tactic == "pragmatique" else "damage_dealt"
            return max(injured, key=lambda m: (
                getattr(contributions[m["player_id"]], metric),
                -(m["hp"] / max(1, m["max_hp"])),
            ))

        def _single_target(pool, E):
            """Cible d'une attaque mono-cible : le provocateur s'il peut être
            frappé (Vaillant), sinon selon l'aggro (cf. THREAT_EXPONENT)."""
            if E["taunted_by"] is not None:
                forced = next((m for m in pool if m["player_id"] == E["taunted_by"]), None)
                if forced is not None:
                    return forced
            weights = [
                ((m["stats"].max_hp + m["stats"].defense * THREAT_DEF_WEIGHT)
                 * (1 + P(m).threat_pct / 100)) ** THREAT_EXPONENT   # Gardien
                for m in pool
            ]
            return random.choices(pool, weights=weights, k=1)[0]

        def _aura_pct() -> float:
            """Aura du Soigneur : +X % de dégâts pour toute l'équipe tant qu'il
            est debout. UNE seule aura par équipe (la plus forte), même avec
            plusieurs Soigneurs."""
            return max(
                (P(m).team_damage_pct for m in alive_party
                 if m["hp"] > 0 and not m["absorbed"] and m["player_id"] != charmed_id),
                default=0.0,
            )

        def _living_allies(member) -> int:
            return sum(1 for m in alive_party
                       if m is not member and m["hp"] > 0 and not m["absorbed"]
                       and m["player_id"] != charmed_id)

        def _check_mob_thresholds(E) -> None:
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
                self._emit("revive", ek(E))
                turn_logs.append(snap(
                    f"👼 {E['mob'].name} renaît à 100% PV, transcendé "
                    f"(+{ab['revive'].get('atk_pct', 0)}% d'attaque) !", focus=E))
            if E["hp"] <= 0 and not E["down"]:
                _foe_down(E)

        def _foe_down(E) -> None:
            """Mort d'un ennemi : explosion (kamikaze), joueurs engloutis
            relâchés, charme levé, Festin de chair."""
            nonlocal charmed_id
            E["down"] = True
            self._emit("ko", ek(E))
            cfg = E["ab"].get("death_explosion")
            victims = [p for p in alive_party if p["hp"] > 0]
            if cfg and victims:
                mult = int(cfg.get("attack_multiplier", 3))
                parts = []
                for target in victims:
                    shield_before = target["shield"]
                    dmg, crit, dodged = self._resolve_mob_hit(
                        E["mob"], target, contributions, title_bonuses_by_player,
                        E["in"], E["family"], extra_multiplier=mult, is_aoe=True)
                    _mob_hit_fx(target, E, dmg, crit, dodged, "explosion", shield_before)
                    target.pop("_recoil", None)  # le monstre est déjà mort
                    target.pop("_mirror", None)
                    target.pop("_freeze", None)
                    if dodged:
                        parts.append(f"{target['name']} esquive")
                    else:
                        tag = " CRIT" if crit else ""
                        dead = " 💀" if target["hp"] <= 0 else ""
                        parts.append(f"{target['name']} −{dmg}{tag}{dead}")
                turn_logs.append(snap(f"💥 {E['mob'].name} explose à sa mort ! " + " · ".join(parts), focus=E))
            for p in alive_party:
                if p["absorbed_by"] == E["i"] and p["hp"] > 0:
                    p["absorbed"] = False
                    p["absorbed_by"] = None
            if charm_foe is E and charmed_id is not None:
                freed = _charmed_member()
                if freed is not None:
                    freed["charmed"] = False
                charmed_id = None
            # Festin de chair : chaque ennemi vaincu rend 25 % des PV max.
            feast = []
            for m in alive_party:
                if (P(m).has("flesh_feast") and m["hp"] > 0 and not m["absorbed"]
                        and m["hp"] < m["max_hp"] and self._spend(m, "flesh_feast")):
                    healed = _heal(m, m, m["max_hp"] * 0.25, allow_buff=False)
                    if healed:
                        feast.append(f"{m['name']} +{healed}")
            if feast:
                turn_logs.append(snap("🍖 Festin de chair : " + " · ".join(feast), focus=E))

        def _hurt_foe(E, amount: int, member, *, through_shield: bool = True,
                      kind: str = "hit", style: str = "magic") -> int:
            """Dégâts DIRECTS à un ennemi (zone, souffle, écho, poison…) : ni
            défense ni esquive ; le bouclier du monstre absorbe d'abord (sauf
            poisons), l'immunité d'un boss ignore les coups trop faibles.
            Comptés dans les dégâts infligés de `member`."""
            if E is None or E["hp"] <= 0 or amount <= 0:
                return 0
            if E["immunity"] > 0 and amount < E["immunity"]:
                self._emit("immune", ek(E))
                return 0
            if through_shield and E["shield"] > 0:
                absorbed = min(E["shield"], amount)
                E["shield"] -= absorbed
                amount -= absorbed
            dealt = min(E["hp"], amount)
            E["hp"] -= dealt
            if member is not None:
                contributions[member["player_id"]].damage_dealt += dealt
            self._emit(kind, ek(E), dealt, source=pk(member) if member is not None else None, style=style)
            _check_mob_thresholds(E)
            return dealt

        def _recoil_to_mob(defender, E) -> None:
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
                contributions[defender["player_id"]].damage_dealt += dealt
                defender[key] = dealt
                self._emit("recoil" if key == "_recoil_dealt" else "mirror", ek(E), dealt,
                           source=pk(defender))
                _check_mob_thresholds(E)

        def _mob_hit_fx(target, E, dmg: int, crit: bool, dodged: bool, style: str,
                        shield_before: int) -> None:
            """Événement d'un coup d'ennemi sur un joueur (esquive, coup, part
            absorbée par le bouclier ou annulée)."""
            src = ek(E)
            if dodged:
                self._emit("dodge", pk(target), source=src)
                return
            absorbed = max(0, shield_before - target["shield"])
            if target.get("_ward"):
                self._emit("block", pk(target), source=src)
            elif dmg > 0 or absorbed == 0:
                self._emit("crit" if crit else "hit", pk(target), dmg, source=src, style=style)
            if absorbed > 0:
                self._emit("block", pk(target), absorbed, source=src)

        def _tags(member) -> str:
            tag = ""
            redirected = member.pop("_redirected", None)
            if redirected:
                tag += f" (🧱 {redirected[0]} encaisse {redirected[1]})"
            if member.pop("_held", False):
                tag += " — tient bon à 1 PV !"
            if member.pop("_ward", False):
                tag += " — 🛡️ coup annulé !"
            if member.pop("_revived", False):
                tag += " — 🧟 revient à la vie !"
            graced = member.pop("_graced", None)
            if graced:
                tag += f" — 😇 relevé par {graced} !"
            if member.pop("_moss", False):
                tag += " — 🌿 la mousse se réveille"
            recoil = member.pop("_recoil_dealt", 0)
            if recoil:
                tag += f" (🔁 {recoil} en contrecoup)"
            mirror = member.pop("_mirror_dealt", 0)
            if mirror:
                tag += f" (🪞 {mirror} renvoyés)"
            return tag + _dry_note(member)

        def _dry_note(member) -> str:
            """« à court de mana », une fois par combat et par joueur."""
            note = ""
            if member.pop("_blood", False):
                note += " — 🩸 pacte de sang"
            ability = member.pop("_dry", None)
            return note + (f" — 💧 à court de mana ({ability})" if ability else "")

        def _has_allies(member) -> bool:
            return any(m is not member and m["hp"] > 0 and not m["absorbed"]
                       and m["player_id"] != charmed_id for m in alive_party)

        # ─── Début du combat : vitesse par allié (Soigneur), boucliers (Égide) ───
        allies_count = max(0, len([m for m in alive_party if m["hp"] > 0]) - 1)
        for m in alive_party:
            if P(m).speed_per_ally and allies_count:
                m["stats"] = replace(m["stats"], speed=m["stats"].speed + P(m).speed_per_ally * allies_count)
        shield_lines = []
        for caster in alive_party:
            pct = P(caster).team_shield_pct
            if pct <= 0 or caster["hp"] <= 0 or not self._spend(caster, "team_shield"):
                continue
            amount = int(round(caster["max_hp"] * pct / 100))
            for m in alive_party:
                if m["hp"] <= 0:
                    continue
                m["shield"] += amount
                self._emit("shield", pk(m), amount, source=pk(caster))
                if m["player_id"] != caster["player_id"]:
                    contributions[caster["player_id"]].hp_healed += amount
            shield_lines.append(f"{caster['name']} ({amount})")
        if shield_lines:
            turn_logs.append(snap("🗿 Égide : bouclier pour tout le groupe — " + " · ".join(shield_lines)))

        round_count = 0

        # ─── Frappe d'ouverture prioritaire (assassin) ───
        for E in foes:
            if "opening_assassinate" not in E["ab"] or E["hp"] <= 0:
                continue
            streak = 0
            while any(p["hp"] > 0 for p in alive_party):
                streak += 1
                target = min((p for p in alive_party if p["hp"] > 0),
                             key=lambda p: (p["hp"], p["max_hp"]))
                shield_before = target["shield"]
                dmg, crit, dodged = self._resolve_mob_hit(
                    E["mob"], target, contributions, title_bonuses_by_player,
                    E["in"], E["family"], extra_multiplier=streak, force_crit=True)
                _mob_hit_fx(target, E, dmg, crit, dodged, "assassinate", shield_before)
                target.pop("_freeze", None)
                _recoil_to_mob(target, E)
                turns += 1
                if dodged:
                    action = f"⚡ {E['mob'].name} fond sur {target['name']} (assassinat) — esquivé !"
                else:
                    mult = f" ×{streak}" if streak > 1 else ""
                    action = f"⚡ {E['mob'].name} assassine {target['name']} : {dmg} dégâts (CRIT{mult})"
                    if target["hp"] <= 0:
                        action += " — 💀 exécuté !"
                    action += _tags(target)
                turn_logs.append(snap(action, focus=E))
                if dodged or target["hp"] > 0 or E["hp"] <= 0:
                    break

        # ─── Défi : le porteur commence en provocation ───
        guard_holder = next((m for m in alive_party if P(m).has("taunt_guard") and m["hp"] > 0
                             and self._spend(m, "taunt_guard")), None)
        if guard_holder is not None:
            _provoke(guard_holder)
            guard_holder["taunt_guard"] = True

        # ─── Charme (succube) ─── (Volonté de fer : immunisé)
        charm_foe = next((E for E in foes if "charm" in E["ab"] and E["hp"] > 0), None)
        if charm_foe is not None:
            living = [p for p in alive_party if p["hp"] > 0 and not P(p).has("iron_will")]
            if not living and any(p["hp"] > 0 for p in alive_party):
                turns += 1
                turn_logs.append(snap(f"💋 {charm_foe['mob'].name} tente de charmer… "
                                      f"mais aucune volonté ne plie !", focus=charm_foe))
            if living:
                charmed = max(living, key=lambda p: _power.calculate_from_stats(p["stats"]))
                charmed_id = charmed["player_id"]
                charmed["charmed"] = True
                name = charm_foe["mob"].name
                if not _party_alive():
                    charmed["hp"] = 0
                    action = (f"💋 {name} charme {charmed['name']}… "
                              f"seul et envoûté, il est dévoré ! Défaite.")
                else:
                    action = (f"💋 {name} charme {charmed['name']} (le plus puissant) ! "
                              f"Retourné contre les siens — abattez-le pour atteindre {name}.")
                turns += 1
                turn_logs.append(snap(action, focus=charm_foe))

        # ─── Absorption (slime) ───
        # Chance d'engloutir tous les joueurs SAUF le plus fort (jamais si un
        # seul joueur), se renforçant de `stat_pct`% de leurs stats. Relâchés
        # si le slime meurt avant la fin du combat.
        for E in foes:
            cfg = E["ab"].get("absorb")
            if not cfg or E["hp"] <= 0:
                continue
            living = [p for p in alive_party if p["hp"] > 0 and not p["absorbed"]]
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
                turns += 1
                turn_logs.append(snap(
                    f"🫧 {E['mob'].name} engloutit {', '.join(names)} et absorbe leurs pouvoirs "
                    f"(+{int(E['bonus_atk'])} atk, +{int(E['bonus_def'])} déf, +{gained_hp} PV) !", focus=E))

        def _strike(player, E, offensive_mult: float = 1.0, prefix: str = "",
                    chained: bool = False, style: str = "slash") -> int:
            """UNE attaque d'un joueur sur l'ennemi E (toute la chaîne de
            dégâts) + ses effets immédiats. Réutilisée par Coup double,
            Riposte, Piqué et Œil de la tempête ; `chained` = coup issu d'un
            autre effet, qui ne déclenche ni zone ni réaction en chaîne.
            Renvoie les dégâts portés aux PV."""
            stats: Stats = player["stats"]
            mine = P(player)
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

            mob_def = _mob_defense_now(E)
            if mine.armor_penetration_pct > 0:  # Léthal
                mob_def = int(mob_def * (1 - min(100.0, mine.armor_penetration_pct) / 100))
            if mine.has("devouring_void"):     # Néant dévorant : un coup sur deux
                player["void_hits"] += 1
                if player["void_hits"] % 2 == 0:
                    mob_def = int(mob_def * 0.5)
            damage, recoil = resolve_hit(raw_attack, mob_def)

            title_bonus = title_bonuses_by_player.get(player["player_id"])
            if title_bonus is not None and E["family"]:
                damage = max(1, round(damage * title_bonus.damage_multiplier_vs(E["family"])))

            elem_mult = E["out"].get(player["player_id"], 1.0)
            if elem_mult != 1.0:
                damage = max(1, round(damage * elem_mult))

            aura = _aura_pct()
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
                allies = min(3, _living_allies(player))
                if allies:
                    damage = max(1, round(damage * (1 + 0.03 * allies)))
            if mine.has("ambush") and not E["acted"]:   # Embuscade
                damage = max(1, round(damage * 1.25))
            if player["shadow"]:  # Pas de l'ombre : prochaine action +10 %
                damage = max(1, round(damage * 1.10))
                player["shadow"] = False

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
                self._emit("dodge", ek(E), source=pk(player))
                damage = 0
                mob_action_text = (f"👻 {mob.name} se dissipe — la première attaque de "
                                   f"{player['name']} est esquivée !")
            elif mob.dodge > 0 and not void_gaze and random.random() < (mob.dodge / 100):
                damage = 0
                self._emit("dodge", ek(E), source=pk(player))
                mob_action_text = f"{mob.name} esquive l'attaque de {player['name']}."
            elif immune:
                self._emit("immune", ek(E), source=pk(player))
                mob_action_text = f"{mob.name} ignore le coup (trop faible)."
            else:
                landed = True
                # Bouclier du mob (gobelin supérieur) : absorbe avant les PV.
                to_shield = min(E["shield"], damage) if E["shield"] > 0 else 0
                E["shield"] -= to_shield
                E["hp"] = max(0, E["hp"] - (damage - to_shield))
                self._emit("crit" if crit else "hit", ek(E), damage, source=pk(player), style=style,
                           element=E["infusion"].get(player["player_id"], ""), shield=to_shield)
                mob_action_text = f"{mob.name} subit l'attaque."

            actual_damage = damage if landed else 0
            contributions[player["player_id"]].damage_dealt += actual_damage
            if landed and mine.has("rising_fury"):
                player["fury"] += 1

            action_text = f"{prefix}{player['name']} inflige {damage} dégâts"
            if len(foes) > 1:
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
                hurt = [m for m in alive_party
                        if m is not player and 0 < m["hp"] < m["max_hp"] and not m["absorbed"]
                        and m["player_id"] != charmed_id]
                amount = actual_damage * mine.ally_heal_on_hit_pct / 100
                if hurt and round(amount) > 0 and self._spend(player, "ally_heal"):
                    ally = min(hurt, key=lambda m: m["hp"] / max(1, m["max_hp"]))
                    mended = _heal(player, ally, amount, allow_buff=False)
                    if mended:
                        action_text += f" ✚ {ally['name']} +{mended}"

            if (mine.lifesteal_pct > 0 and round(actual_damage * mine.lifesteal_pct / 100) > 0  # Vampire
                    and player["hp"] < player["max_hp"] and self._spend(player, "lifesteal")):
                stolen = _heal(player, player, actual_damage * mine.lifesteal_pct / 100,
                               allow_buff=False)
                if stolen:
                    action_text += f" 🧛 +{stolen}"
            # Soif écarlate : un critique soigne de 20 % des dégâts infligés.
            if (crit and mine.has("scarlet_thirst") and round(actual_damage * 0.20) > 0
                    and player["hp"] < player["max_hp"] and self._spend(player, "scarlet_thirst")):
                drunk = _heal(player, player, actual_damage * 0.20, allow_buff=False)
                if drunk:
                    action_text += f" 🍷 +{drunk}"

            # Vaillant : seulement s'il y a un allié à protéger et qu'aucune
            # provocation n'attend déjà le prochain coup des ennemis — elle ne
            # vaut que pour celui-là : la reprendre gaspillait le mana (trois
            # Vaillant se la volaient en boucle, mesuré le 25/10/2026).
            if (mine.taunt_chance_pct > 0 and not _taunters() and _has_allies(player)
                    and random.random() < mine.taunt_chance_pct / 100 and self._spend(player, "taunt")):
                _provoke(player)
                action_text += " 🫀 provoque"

            if E["reflect_pct"] > 0 and actual_damage > 0:
                reflected = max(1, round(actual_damage * E["reflect_pct"] / 100))
                self._apply_player_damage(player, reflected, use_shield=False)
                self._emit("hit", pk(player), reflected, source=ek(E), style="reflect")
                action_text += f" (renvoi {reflected})"

            # Contrecoup : la DEF du monstre en trop revient au joueur (coup
            # arrivé sur l'armure, immunité comprise ; pas sur une esquive).
            if recoil > 0 and (landed or immune):
                taken = self._apply_player_damage(player, recoil, use_shield=False)
                self._emit("recoil", pk(player), taken, source=ek(E))
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
                    for N in _neighbours(E)
                    if (dealt := _hurt_foe(N, max(1, round(actual_damage * mine.splash_damage_pct / 100)),
                                           player, style="splash"))
                ]
                if splashed:
                    action_text += " 🔮 " + ", ".join(splashed)

            # Souffle ancestral : exécute une cible (hors boss) sous 20 % de PV.
            if (landed and mine.has("ancestral_breath") and 0 < E["hp"] < E["max_hp"] * 0.20
                    and not E["is_boss"] and self._spend(player, "ancestral_breath")):
                contributions[player["player_id"]].damage_dealt += E["hp"]
                self._emit("execute", ek(E), E["hp"], source=pk(player))
                E["hp"] = 0
                action_text += " 🐉 exécuté !"

            action_text += _dry_note(player)
            turn_logs.append(snap(mob_action_text, players=[action_text], focus=E))
            _check_mob_thresholds(E)
            return actual_damage

        def _tick_dots(p) -> None:
            """Saignement (ogre) et poison : UNE fois par action de la victime.

            Avant (audit oct. 2026) ils tombaient à chaque TICK de jauge, soit
            ~10-20 fois par action : un poison « 3 tours » durait 3 ticks, se
            renouvelait à chaque coup et doublait les dégâts du monstre — et
            chaque tick comptait comme une action (escalade avancée)."""
            lines = []
            pz = p.get("poison")
            if pz:
                self._apply_player_damage(p, pz["dmg"], use_shield=False)
                self._emit("dot", pk(p), pz["dmg"], style="poison")
                contributions[p["player_id"]].damage_tanked += pz["dmg"]
                lines.append(f"☠️ Poison : {p['name']} −{pz['dmg']}")
                pz["turns"] -= 1
                if pz["turns"] <= 0:
                    p["poison"] = None
            if p["bleeds"] and p["hp"] > 0:
                total = sum(b["dmg"] for b in p["bleeds"])
                self._apply_player_damage(p, total, use_shield=False)
                self._emit("dot", pk(p), total, style="bleed")
                contributions[p["player_id"]].damage_tanked += total
                lines.append(f"🩸 Saignement : {p['name']} −{total}")
                for b in p["bleeds"]:
                    b["turns"] -= 1
                p["bleeds"] = [b for b in p["bleeds"] if b["turns"] > 0]
            if lines:
                turn_logs.append(snap(" · ".join(lines) + (" 💀" if p["hp"] <= 0 else "")))

        def _member(player_id):
            return next((m for m in alive_party if m["player_id"] == player_id), None)

        def _void_echo(player) -> None:
            """Échos du vide : toutes les 8 actions, un écho frappe la cible
            (50 % de l'ATK, sans défense) et absorbe le prochain coup reçu."""
            if (not P(player).has("void_echo") or player["actions"] % 8 or not _foes_alive()
                    or not self._spend(player, "void_echo")):
                return
            target = _player_target()
            dealt = _hurt_foe(target, max(1, round(player["stats"].attack * 0.50)), player, style="void")
            player["void_ward"] = True
            turn_logs.append(snap(f"🌀 Écho du vide de {player['name']} : {target['mob'].name} −{dealt}, "
                                  f"le prochain coup reçu sera absorbé.", focus=target))

        def _tick_foe_dots(E) -> None:
            """Poison, brûlures et saignements posés par les joueurs : une fois
            par action de l'ennemi (même règle que pour les joueurs). Ils
            ignorent son bouclier et sa défense."""
            lines = []
            pz = E["poison"]
            if pz:
                dealt = _hurt_foe(E, pz["dmg"], _member(pz["by"]), through_shield=False,
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
                    total += _hurt_foe(E, dot["dmg"], _member(dot["by"]), through_shield=False,
                                       kind="dot", style="burn" if key == "burns" else "bleed")
                    dot["turns"] -= 1
                E[key] = [d for d in E[key] if d["turns"] > 0]
                lines.append(f"{label} : −{total}")
            if lines:
                turn_logs.append(snap(f"{E['mob'].name} — " + " · ".join(lines)
                                      + (" 💀" if E["hp"] <= 0 else ""), focus=E))

        while _foes_alive() and _party_alive():
            round_count += 1
            if ((max_turns and turns >= max_turns) or (max_ticks and round_count > max_ticks)
                    or turns >= hard_max):
                break
            for E in foes:
                _escalate(E)

            for player in alive_party:
                if player["hp"] > 0 and not player["absorbed"]:
                    fill = player["stats"].speed
                    if P(player).has("lunar_rage") and player["hp"] < player["max_hp"] * 0.5:
                        fill = round(fill * 1.15)    # Rage lunaire
                    if player["slow"] > 0:
                        fill = max(1, fill // 2)   # ralenti (momie) : jauge à 50%
                    player["gauge"] += fill

            for E in _living_foes():
                fill = E["mob"].speed
                if E["slow_pct"]:   # Étreinte astrale
                    fill = max(1, round(fill * (1 - E["slow_pct"] / 100))) if fill > 0 else 0
                E["gauge"] += fill
            acted = False

            for player in alive_party:
                while (player["gauge"] >= 100 and player["hp"] > 0 and _foes_alive()
                       and turns < hard_max):
                    _tick_dots(player)
                    if player["hp"] <= 0:
                        break
                    # Mousse vivace : 10 % des PV max à chacune de ses actions.
                    if player["moss"] > 0:
                        player["moss"] -= 1
                        healed = _heal(player, player, player["max_hp"] * 0.10, allow_buff=False)
                        if healed:
                            turn_logs.append(snap(f"🌿 Mousse vivace : {player['name']} +{healed} PV"))
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
                        dmg, crit, dodged, recoil = self._pvp_hit(player, victim, contributions)
                        self._emit("dodge" if dodged else ("crit" if crit else "hit"), pk(victim), dmg,
                                   source=pk(player), style="charm")
                        act = (f"😈 {player['name']} (charmé) attaque {victim['name']} — esquive !"
                               if dodged else
                               f"😈 {player['name']} (charmé) frappe {victim['name']} : {dmg} dégâts"
                               + (" CRIT" if crit else "")
                               + (" 💀" if victim["hp"] <= 0 else "")
                               + (f" (🔁 {recoil} en contrecoup)" if recoil else ""))
                        turn_logs.append(snap(act))
                        continue

                    turns += 1
                    acted = True
                    player["gauge"] -= 100
                    player["actions"] += 1
                    if player["slow"] > 0:
                        player["slow"] -= 1

                    # Charme : les non-charmés doivent d'abord abattre le charmé.
                    if _charmed_alive():
                        victim = _charmed_member()
                        dmg, crit, dodged, recoil = self._pvp_hit(player, victim, contributions)
                        self._emit("dodge" if dodged else ("crit" if crit else "hit"), pk(victim), dmg,
                                   source=pk(player), style="slash")
                        freed = victim["hp"] <= 0 and not dodged
                        act = (f"{player['name']} vise {victim['name']} (charmé) — esquive !"
                               if dodged else
                               f"{player['name']} frappe {victim['name']} (charmé) : {dmg} dégâts"
                               + (" CRIT" if crit else "")
                               + (f" (🔁 {recoil} en contrecoup)" if recoil else "")
                               + (f" — 💔 {victim['name']} est libéré !" if freed else ""))
                        turn_logs.append(snap(act))
                        continue

                    stats: Stats = player["stats"]
                    mine = P(player)

                    # Soigneur : le sort de soin REMPLACE l'attaque quand un
                    # allié est sous HEAL_BELOW_PCT % de ses PV ; sinon il attaque
                    # (avant, il soignait dès qu'il manquait 1 PV : seul, il ne
                    # frappait presque jamais).
                    if mine.healer:
                        heal_target = _heal_target(player)
                        if heal_target is not None and self._spend(player, "heal_spell"):
                            amount = stats.attack * BASE_HEAL_PCT / 100 * mine.heal_power_multiplier
                            healed = _heal(player, heal_target, amount)
                            who = "se soigne" if heal_target is player else f"soigne {heal_target['name']}"
                            turn_logs.append(snap(f"{_focus()['mob'].name} observe.", players=[
                                f"💚 {player['name']} {who} : +{healed} PV "
                                f"(💧 {player['mana']}/{player['mana_max']})" + _dry_note(player)]))
                            _void_echo(player)
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
                        for E in _living_foes():
                            _strike(player, E, offensive_mult, prefix="🌩️ Œil de la tempête — ",
                                    chained=True, style="storm")
                            if E["hp"] > 0 and not E["is_boss"] and random.random() < 0.50:
                                E["stunned"] = True
                                self._emit("stun", ek(E))
                                turn_logs.append(snap(f"💫 {E['mob'].name} est étourdi par la tempête.",
                                                      focus=E))
                    # Piqué : la première attaque frappe trois fois, à 60 %.
                    elif mine.has("dive") and not player["dived"]:
                        player["dived"] = True
                        for _ in range(3):
                            target = _player_target()
                            if target is None:
                                break
                            _strike(player, target, offensive_mult * 0.60, prefix="🦅 Piqué — ", style="dive")
                    else:
                        _strike(player, _player_target(), offensive_mult)
                    player["attacks"] += 1
                    # Coup double : 10 % de chance d'attaquer une 2e fois (jamais en chaîne).
                    if (mine.has("double_strike") and _foes_alive() and random.random() < 0.10
                            and self._spend(player, "double_strike")):
                        _strike(player, _player_target(), prefix="⚡ Coup double — ", chained=True,
                                style="double")
                    # Souffle juvénile : toutes les 5 attaques, des flammes
                    # frappent tous les ennemis (30 % de l'ATK, sans défense).
                    if (mine.has("young_breath") and player["attacks"] % 5 == 0 and _foes_alive()
                            and self._spend(player, "young_breath")):
                        burnt = [f"{E['mob'].name} −{_hurt_foe(E, max(1, round(stats.attack * 0.30)), player, style='fire')}"
                                 for E in _living_foes()]
                        turn_logs.append(snap("🔥 Souffle juvénile de "
                                              f"{player['name']} : " + " · ".join(burnt)))
                    _void_echo(player)

                    for eff in turn_effects:
                        if eff.kind == SKILL_KIND_SHIELD_SELF:
                            player["shield"] += int(stats.defense * eff.value)
                        elif eff.kind == SKILL_KIND_HEAL_ALLY:
                            heal_amt = int(stats.attack * eff.value)
                            allies = [m for m in alive_party
                                      if m["player_id"] != player["player_id"] and m["hp"] > 0]
                            if heal_amt > 0 and allies:
                                target_ally = min(allies, key=lambda m: m["hp"])
                                _heal(player, target_ally,
                                      heal_amt * mine.heal_power_multiplier)
                        elif eff.kind == SKILL_KIND_SHIELD_TEAM:
                            shield_amt = int(stats.defense * eff.value)
                            if shield_amt > 0:
                                for m in alive_party:
                                    if m["hp"] <= 0:
                                        continue
                                    m["shield"] += shield_amt
                                    if m["player_id"] != player["player_id"]:
                                        contributions[player["player_id"]].hp_healed += shield_amt

                    if not _foes_alive():
                        break

            # ── Tour des ennemis ──
            for E in foes:
                if E["hp"] <= 0:
                    continue
                if E is charm_foe and _charmed_alive():
                    E["gauge"] = 0  # succube protégée, passive tant que le charmé vit
                _escalate(E)
                ab = E["ab"]
                foe_actions = 0
                # Garde-fou hard_max aussi ICI : l'escalade multiplie la
                # vitesse du monstre, qui pourrait sinon agir des millions de
                # fois dans un seul tick.
                while (E["gauge"] >= 100 and E["hp"] > 0 and _party_alive()
                       and not (E is charm_foe and _charmed_alive()) and turns < hard_max):
                    turns += 1
                    acted = True
                    E["gauge"] -= 100
                    foe_actions += 1
                    E["acted"] = True
                    _tick_foe_dots(E)
                    if E["hp"] <= 0:
                        break
                    if E["atk_down"]:
                        E["atk_down"] -= 1
                    # Étourdi / gelé par un joueur : perd cette action.
                    if E["stunned"]:
                        E["stunned"] = False
                        E["taunted_by"] = None
                        self._emit("stun", ek(E))
                        turn_logs.append(snap(f"💫 {E['mob'].name} est étourdi et perd son action.",
                                              focus=E))
                        continue

                    # Chaman : soin d'urgence (remplace l'attaque de ce tour).
                    if E["chaman_pending"]:
                        E["chaman_pending"] = False
                        before = E["hp"]
                        if anti_heal:
                            E["hp"] += (E["max_hp"] - E["hp"]) // 2
                            turn_logs.append(snap(f"✨ {E['mob'].name} canalise… le soin est entravé (Anti-soin) !",
                                                  focus=E))
                        else:
                            E["hp"] = E["max_hp"]
                            self._emit("heal", ek(E), E["hp"] - before)
                            turn_logs.append(snap(f"✨ {E['mob'].name} canalise et se soigne à 100% PV !",
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
                    atk_now = _mob_attack_now(E)

                    for _ in range(hits):
                        pool = _mob_targets()
                        if not pool or E["hp"] <= 0:   # un contrecoup a pu l'achever
                            break
                        targets = pool if aoe else [_single_target(pool, E)]
                        parts = []
                        for target in targets:
                            shield_before = target["shield"]
                            dmg, mob_crit, dodged = self._resolve_mob_hit(
                                E["mob"], target, contributions, title_bonuses_by_player,
                                E["in"], E["family"],
                                extra_multiplier=single_mult, attack_override=atk_now,
                                is_aoe=aoe)
                            _mob_hit_fx(target, E, dmg, mob_crit, dodged, "aoe" if aoe else "melee",
                                        shield_before)
                            # Vol de vie (gargouille) — divisé par deux par Anti-soin
                            if not dodged and dmg > 0 and "lifesteal" in ab and E["hp"] > 0:
                                heal = round(dmg * ab["lifesteal"].get("pct", 0) / 100)
                                if anti_heal:
                                    heal //= 2
                                if heal > 0:
                                    before = E["hp"]
                                    E["hp"] = min(E["max_hp"], E["hp"] + heal)
                                    self._emit("heal", ek(E), E["hp"] - before)
                            # Contrecoup (Épines compris) : la DEF en trop frappe le monstre.
                            _recoil_to_mob(target, E)
                            # Riposte : 10 % de chance de contre-attaquer (jamais en chaîne).
                            if (not dodged and target["hp"] > 0 and E["hp"] > 0
                                    and P(target).has("counter_attack") and random.random() < 0.10
                                    and self._spend(target, "counter_attack")):
                                _strike(target, E, prefix="↩️ Riposte — ", chained=True, style="counter")
                            # Morsure du givre : l'attaquant (hors boss) perd sa prochaine action.
                            frozen_now = False
                            if (target.pop("_freeze", False) and E["hp"] > 0 and not E["is_boss"]
                                    and not E["stunned"] and self._spend(target, "frost_bite")):
                                E["stunned"] = True
                                frozen_now = True
                                self._emit("stun", ek(E), style="freeze")
                            # Étourdissement (gobelin géant / banshee) — non cumulable
                            stunned_now = False
                            if not dodged and "stun" in ab and not target["stunned"]:
                                if random.random() < ab["stun"].get("chance", 0) / 100:
                                    target["stunned"] = True
                                    stunned_now = True
                                    self._emit("stun", pk(target), source=ek(E))
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
                                tag += _tags(target)
                                parts.append(f"{target['name']} −{dmg}{tag}")
                        verb = "déchaîne une frappe de zone" if aoe else "frappe"
                        heal_tag = " (vol de vie)" if "lifesteal" in ab else ""
                        turn_logs.append(snap(f"{E['mob'].name} {verb}{heal_tag} : " + " · ".join(parts),
                                              focus=E))
                        if not _party_alive():
                            break

                    # Réaction en chaîne (gobelin ballon) : chaque salve peut se répliquer.
                    if "chain_replicate" in ab and _party_alive() and E["hp"] > 0:
                        chance = ab["chain_replicate"].get("chance", 20) / 100
                        rep = 0
                        while _party_alive() and random.random() < chance and rep < 15:
                            rep += 1
                            pool = _mob_targets()
                            if not pool:
                                break
                            rtargets = pool if aoe else [_single_target(pool, E)]
                            parts = []
                            for target in rtargets:
                                shield_before = target["shield"]
                                dmg, mob_crit, dodged = self._resolve_mob_hit(
                                    E["mob"], target, contributions, title_bonuses_by_player,
                                    E["in"], E["family"],
                                    extra_multiplier=single_mult, attack_override=atk_now,
                                    is_aoe=aoe)
                                _mob_hit_fx(target, E, dmg, mob_crit, dodged, "explosion", shield_before)
                                target.pop("_freeze", None)
                                _recoil_to_mob(target, E)
                                parts.append(f"{target['name']} esquive" if dodged
                                             else f"{target['name']} −{dmg}"
                                             + (" 💀" if target["hp"] <= 0 else "")
                                             + _tags(target))
                            turns += 1
                            turn_logs.append(snap(f"💥 Réaction en chaîne (réplique {rep}) : "
                                                  + " · ".join(parts), focus=E))

                    # La provocation ne vaut que pour la PROCHAINE attaque.
                    E["taunted_by"] = None
                    if not _party_alive():
                        break

                # Effets « à chaque tour de l'ennemi » : un passage par action
                # jouée pendant ce tick (pas un par tick).
                for _ in range(foe_actions):
                    E["turn_count"] += 1
                    if E["hp"] <= 0 or not _party_alive():
                        break
                    # Invocations (adds) : une de plus tous les `summon_turn_interval`
                    # tours, chacune frappe un joueur au hasard.
                    if E["adds_attack"] > 0 and E["adds_interval"] > 0 and E["adds_max"] > 0:
                        if E["turn_count"] % E["adds_interval"] == 0 and E["active_adds"] < E["adds_max"]:
                            E["active_adds"] += 1
                        for _ in range(E["active_adds"]):
                            alive = [p for p in alive_party if p["hp"] > 0]
                            if not alive:
                                break
                            victim = random.choice(alive)
                            # Même formule ; pas de contrecoup : une invocation
                            # n'a pas de PV à elle.
                            add_dmg, _ = resolve_hit(E["adds_attack"], victim["stats"].defense)
                            taken = self._apply_player_damage(victim, add_dmg)
                            self._emit("hit", pk(victim), taken, source=ek(E), style="summon")
                            contributions[victim["player_id"]].damage_tanked += E["adds_attack"]
                    # Régénération (monstres des zones hautes) : % des PV max par action.
                    if "regen" in ab and E["hp"] < E["max_hp"]:
                        heal = round(E["max_hp"] * ab["regen"].get("pct", 3) / 100)
                        heal = heal // 2 if anti_heal else heal
                        before = E["hp"]
                        E["hp"] = min(E["max_hp"], E["hp"] + heal)
                        self._emit("heal", ek(E), E["hp"] - before)
                    # Auto-soin du boss.
                    if E["heal_per_turn"] > 0:
                        heal = E["heal_per_turn"] // 2 if anti_heal else E["heal_per_turn"]
                        before = E["hp"]
                        E["hp"] = min(E["max_hp"], E["hp"] + heal)
                        self._emit("heal", ek(E), E["hp"] - before)
                if not _party_alive():
                    break

            if not acted:
                continue

        for member in alive_party:
            contribution = contributions[member["player_id"]]
            contribution.final_hp = member["hp"]
            contribution.final_mana = member["mana"]
            contribution.mana_max = member["mana_max"]
            contribution.survived = member["hp"] > 0

        surviving_players = [player["name"] for player in alive_party if player["hp"] > 0]
        defeated_players = [player["name"] for player in alive_party if player["hp"] <= 0]
        victory = not _foes_alive()
        names = [E["base"].name for E in foes]
        mob_name = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " et " + names[-1]

        return PartyBattleResult(
            victory=victory,
            turns=turns,
            mob_name=mob_name,
            mob_image_name=foes[0]["base"].image_name,
            mob_remaining_hp=sum(max(0, E["hp"]) for E in foes),
            surviving_players=surviving_players,
            defeated_players=defeated_players,
            xp_gained=sum(E["base"].xp_reward for E in foes) if victory else 0,
            gold_gained=sum(E["base"].gold_reward for E in foes) if victory else 0,
            summary=(
                f"Le groupe a vaincu {mob_name} en {turns} action(s)."
                if victory
                else f"Le groupe a été vaincu par {mob_name}."
            ),
            turn_logs=turn_logs,
            contributions=list(contributions.values()),
            enemies=[
                {"code": E["base"].code, "name": E["base"].name, "max_hp": E["max_hp"],
                 "remaining_hp": max(0, E["hp"]), "defeated": E["hp"] <= 0}
                for E in foes
            ],
        )

    # ------------------------------------------------------------------ helpers
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

    # ------------------------------------------------------------ affichage
    def _emit(self, kind: str, target: str, amount: int = 0, source: str | None = None,
              **extra) -> None:
        """Note un événement de l'action en cours pour l'affichage (chiffres,
        effets) : `kind` hit / crit / dodge / immune / block / heal / shield /
        dot / recoil / mirror / stun / ko / revive / hold / execute / enrage ;
        `target` / `source` = "p<joueur>" ou "e<index de l'ennemi>"."""
        events = getattr(self, "_events", None)
        if events is None:
            return
        event = {"kind": kind, "target": target, "amount": int(amount)}
        if source:
            event["source"] = source
        event.update({k: v for k, v in extra.items() if v not in (None, "", 0)})
        events.append(event)

    def _take_events(self) -> list[dict]:
        events = getattr(self, "_events", None) or []
        self._events = []
        return events

    # ------------------------------------------------------------ passifs
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

    def _snapshot(self, turns, player_actions, mob_action, alive_party, foes, focus,
                  events: list[dict] | None = None) -> PartyBattleTurnLog:
        """Construit un PartyBattleTurnLog (état complet équipe + ennemis)
        pour un tour. `mob_state` = l'ennemi concerné par l'action (le seul,
        hors meute) ; `enemies_state` = tous, dans l'ordre de la formation."""
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
            mob_state=self._enemy_state(focus),
            enemies_state=[self._enemy_state(E) for E in foes] if len(foes) > 1 else [],
            events=events or [],
        )
