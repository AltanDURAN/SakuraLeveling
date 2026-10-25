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
#: world boss sont conservés d'un jour à l'autre.
ESCALATION_START = 25    # 1er palier à la 30e action du monstre (25 + 5)
ESCALATION_EVERY = 5
ESCALATION_STEP = 0.10

#: Garde-fou absolu du nombre d'actions, en dernier recours si l'escalade ne
#: suffit pas (ex. Soigneurs qui soignent tout). Atteint ⇒ monstre non vaincu.
HARD_MAX_TURNS = 500

#: Aggro : un monstre vise de préférence le joueur le plus SOLIDE (PV max +
#: DEF × 25, la robustesse du power score), poids à la puissance 3 — un tank
#: deux fois plus robuste qu'un DPS prend 8 fois plus de coups que lui. Avant
#: (25/10/2026), la cible était tirée au hasard : le tank ne protégeait
#: personne. La provocation reste prioritaire.
THREAT_DEF_WEIGHT = 25
THREAT_EXPONENT = 3


def escalation_multiplier(mob_actions: int) -> float:
    """Multiplicateur cumulé des stats du monstre après `mob_actions` actions
    du monstre."""
    mult = 1.0
    for level in range(1, max(0, mob_actions - ESCALATION_START) // ESCALATION_EVERY + 1):
        mult *= 1 + ESCALATION_STEP * level
    return mult


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
        # max_ticks  : limite de TEMPS (ticks de jauge) plutôt que d'actions —
        #              la vitesse compte (épreuve DPS : « 40 s de combat »).
        # escort_ids : le monstre ne vise QUE ces joueurs, et le combat
        #              s'arrête dès que l'un d'eux tombe (épreuve de soutien).
        # mana_costs : coûts des compétences actives (défaut MANA_COSTS ;
        #              les outils de mesure passent {} pour compter sans limite).
        title_bonuses_by_player = title_bonuses_by_player or {}
        elemental_mult_by_player = elemental_mult_by_player or {}
        incoming_elemental_mult_by_player = incoming_elemental_mult_by_player or {}
        skill_loadouts_by_player = skill_loadouts_by_player or {}
        ab = mob_abilities or {}
        passives_by_player = passives_by_player or {}
        tactics_by_player = tactics_by_player or {}
        self._passives = passives_by_player
        self._mana_costs = MANA_COSTS if mana_costs is None else mana_costs
        _skill_svc = SkillEffectService()

        def P(member) -> CombatPassives:
            return passives_by_player.get(member["player_id"], NO_PASSIVES)
        mob_family = mob.family or ""
        base_mob = mob
        escalation_level = 0
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

        # ── État du charme (succube) ──
        charmed_id: int | None = None
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

        # ── État des capacités du monstre ──
        # Stats effectives (max HP + bonus d'absorption du slime).
        mob_max_hp = mob.max_hp
        mob_bonus_atk = 0.0
        mob_bonus_def = 0.0
        mob_shield = mob.max_hp if "shield" in ab else 0
        mob_revived = False
        chaman_pending = False
        chaman_done = False
        liche_single_next = False               # commence par une frappe de zone
        fantome_first_dodged: set[int] = set()

        def _enrage_pct() -> int:
            tiers = ab.get("enrage", {}).get("tiers", [])
            if not tiers or not mob_max_hp:
                return 0
            ratio = mob_hp / mob_max_hp * 100
            return max((b for t, b in tiers if ratio <= t), default=0)

        def _mob_attack_now() -> int:
            a = float(mob.attack) + mob_bonus_atk
            if mob_revived:
                a *= 1 + ab.get("revive", {}).get("atk_pct", 0) / 100
            a *= 1 + _enrage_pct() / 100
            return max(1, int(round(a)))

        def _mob_defense_now() -> int:
            d = float(mob.defense) + mob_bonus_def
            if mob_revived:
                d *= 1 + ab.get("revive", {}).get("def_pct", 0) / 100
            # La furie ne touche PAS la défense : en combat soustractif, une DEF
            # qui approche l'ATK des joueurs met chaque coup au plancher de 1
            # (l'Archidémon était imbattable même à 4, audit du 24/10/2026).
            return int(round(d))

        def _escalate() -> None:
            """Applique le palier d'escalade atteint (cf. ESCALATION_EVERY)."""
            nonlocal mob, escalation_level
            level = max(0, boss_turn_count - ESCALATION_START) // ESCALATION_EVERY
            if level <= escalation_level or mob_hp <= 0:
                return
            escalation_level = level
            mult = escalation_multiplier(boss_turn_count)
            mob = replace(
                base_mob,
                attack=max(1, round(base_mob.attack * mult)),
                defense=round(base_mob.defense * mult),
                speed=max(1, round(base_mob.speed * mult)),
                crit_chance=min(100, base_mob.crit_chance * mult),
                crit_damage=max(100, base_mob.crit_damage * mult),
                current_hp=mob_hp,
            )
            turn_logs.append(snap(
                f"🔥 Le combat s'éternise : {mob.name} se renforce "
                f"(+{round(ESCALATION_STEP * level * 100)} %, ×{mult:.2f} au total)"))

        def snap(action, players=None):
            return self._snapshot(turns, players or [], action, alive_party, mob, mob_hp,
                                  mob_shield, mob_max_hp)

        # ── Passifs : soins, provocation (cf. combat_passives) ──
        taunter_id: int | None = None

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
            un allié frappent l'ennemi. Pas de l'ombre : prochain soin +10 %."""
            nonlocal mob_hp
            if amount <= 0 or target["hp"] <= 0:
                return 0
            if P(healer).has("healing_hands"):
                amount *= 1.10
            if allow_buff and healer["shadow"]:
                amount *= 1.10
                healer["shadow"] = False
            amount *= 1 + P(target).heal_received_pct / 100
            before = target["hp"]
            target["hp"] = min(target["max_hp"], target["hp"] + int(round(amount)))
            healed = target["hp"] - before
            if healer["player_id"] != target["player_id"]:
                contributions[healer["player_id"]].hp_healed += healed
                if P(healer).has("healing_hands") and healed > 0 and mob_hp > 0:
                    splash = max(1, round(healed * 0.10))
                    mob_hp = max(0, mob_hp - splash)
                    contributions[healer["player_id"]].damage_dealt += splash
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

        def _single_target(pool):
            """Cible d'une attaque mono-cible : le dernier provocateur s'il peut
            être frappé (Vaillant), sinon selon l'aggro (cf. THREAT_EXPONENT)."""
            if taunter_id is not None:
                forced = next((m for m in pool if m["player_id"] == taunter_id), None)
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

        def _check_mob_thresholds() -> None:
            """Seuils de PV du monstre, quelle que soit la source des dégâts
            (coup, contrecoup) : soin d'urgence du chaman, résurrection."""
            nonlocal mob_hp, mob_revived, chaman_pending, chaman_done
            # Chaman : 1ʳᵉ fois sous 50% PV → soin d'urgence au prochain tour.
            if ("heal_once_below" in ab and not chaman_done and mob_hp > 0
                    and mob_hp <= mob_max_hp * ab["heal_once_below"].get("hp_pct", 50) / 100):
                chaman_pending = True
                chaman_done = True
            # Résurrection (ange déchu) : 1ʳᵉ mort → revient à 100% PV.
            if mob_hp <= 0 and "revive" in ab and not mob_revived:
                mob_revived = True
                mob_hp = mob_max_hp
                turn_logs.append(snap(
                    f"👼 {mob.name} renaît à 100% PV, transcendé "
                    f"(+{ab['revive'].get('atk_pct', 0)}% d'attaque) !"))

        def _recoil_to_mob(defender) -> None:
            """Contrecoup : la défense du joueur en trop renvoie des dégâts au
            monstre (cf. damage_formula). Ni action, ni effet déclenché ; le
            bouclier du monstre ne l'arrête pas. Compté dans les dégâts infligés."""
            nonlocal mob_hp
            recoil = defender.pop("_recoil", 0)
            if recoil <= 0 or mob_hp <= 0:
                return
            dealt = min(mob_hp, recoil)
            mob_hp -= dealt
            contributions[defender["player_id"]].damage_dealt += dealt
            defender["_recoil_dealt"] = dealt
            _check_mob_thresholds()

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
            recoil = member.pop("_recoil_dealt", 0)
            if recoil:
                tag += f" (🔁 {recoil} en contrecoup)"
            return tag + _dry_note(member)

        def _dry_note(member) -> str:
            """« à court de mana », une fois par combat et par joueur."""
            ability = member.pop("_dry", None)
            return f" — 💧 à court de mana ({ability})" if ability else ""

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
                if m["player_id"] != caster["player_id"]:
                    contributions[caster["player_id"]].hp_healed += amount
            shield_lines.append(f"{caster['name']} ({amount})")
        if shield_lines:
            turn_logs.append(snap("🗿 Égide : bouclier pour tout le groupe — " + " · ".join(shield_lines)))

        # ── État des modifiers boss dynamiques (neutres hors world boss) ──
        # Un MONSTRE peut aussi invoquer ou renvoyer des dégâts (capacités
        # `summon` / `reflect`, zones C → S) : même mécanique que les boss.
        if "summon" in ab and not boss_adds:
            sm = ab["summon"]
            boss_adds = {
                "attack": max(1, round(mob.attack * sm.get("atk_pct", 30) / 100)),
                "summon_turn_interval": sm.get("every", 3),
                "max_active": sm.get("max", 2),
            }
        if "reflect" in ab:
            boss_reflect_pct = max(boss_reflect_pct, int(ab["reflect"].get("pct", 0)))
        boss_adds = boss_adds or {}
        adds_attack = int(boss_adds.get("attack", 0))
        adds_interval = int(boss_adds.get("summon_turn_interval", 0))
        adds_max = int(boss_adds.get("max_active", 0))
        active_adds = 0
        round_count = 0
        # Tours JOUÉS par le boss : base du soin et des invocations. La boucle
        # avance par TICKS de jauge (un combattant agit tous les 100/vitesse
        # ticks) : appliquer ces effets à chaque tick les multipliait par ~10-20.
        boss_turn_count = 0

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
                _recoil_to_mob(target)
                turns += 1
                if dodged:
                    action = f"⚡ {mob.name} fond sur {target['name']} (assassinat) — esquivé !"
                else:
                    mult = f" ×{streak}" if streak > 1 else ""
                    action = f"⚡ {mob.name} assassine {target['name']} : {dmg} dégâts (CRIT{mult})"
                    if target["hp"] <= 0:
                        action += " — 💀 exécuté !"
                    action += _tags(target)
                turn_logs.append(snap(action))
                if dodged or target["hp"] > 0 or mob_hp <= 0:
                    break

        # ─── Défi : le porteur commence en provocation ───
        guard_holder = next((m for m in alive_party if P(m).has("taunt_guard") and m["hp"] > 0
                             and self._spend(m, "taunt_guard")), None)
        if guard_holder is not None:
            taunter_id = guard_holder["player_id"]
            guard_holder["taunt_guard"] = True

        # ─── Charme (succube) ─── (Volonté de fer : immunisé)
        if "charm" in ab and mob_hp > 0:
            living = [p for p in alive_party if p["hp"] > 0 and not P(p).has("iron_will")]
            if not living and any(p["hp"] > 0 for p in alive_party):
                turns += 1
                turn_logs.append(snap(f"💋 {mob.name} tente de charmer… mais aucune volonté ne plie !"))
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

        # ─── Absorption (slime) ───
        # Chance d'engloutir tous les joueurs SAUF le plus fort (jamais si un
        # seul joueur), se renforçant de `stat_pct`% de leurs stats.
        cfg = ab.get("absorb")
        if cfg and mob_hp > 0:
            living = [p for p in alive_party if p["hp"] > 0]
            if len(living) > 1 and random.random() < cfg.get("chance", 10) / 100:
                strongest = max(living, key=lambda p: _power.calculate_from_stats(p["stats"]))
                pct = cfg.get("stat_pct", 50) / 100
                names, gained_hp = [], 0
                for p in living:
                    if p["player_id"] == strongest["player_id"]:
                        continue
                    p["absorbed"] = True
                    mob_bonus_atk += p["stats"].attack * pct
                    mob_bonus_def += p["stats"].defense * pct
                    gained_hp += int(p["max_hp"] * pct)
                    names.append(p["name"])
                mob_max_hp = mob.max_hp + gained_hp
                mob_hp = min(mob_max_hp, mob_hp + gained_hp)
                turns += 1
                turn_logs.append(snap(
                    f"🫧 {mob.name} engloutit {', '.join(names)} et absorbe leurs pouvoirs "
                    f"(+{int(mob_bonus_atk)} atk, +{int(mob_bonus_def)} déf, +{gained_hp} PV) !"))

        def _strike(player, offensive_mult: float = 1.0, special_proc: bool = False,
                    prefix: str = "") -> None:
            """UNE attaque d'un joueur sur le monstre (toute la chaîne de dégâts)
            + ses effets immédiats. Réutilisée par Coup double et Riposte, qui
            ne se déclenchent jamais en chaîne."""
            nonlocal mob_hp, mob_shield, taunter_id, chaman_pending, chaman_done, mob_revived
            stats: Stats = player["stats"]
            mine = P(player)
            raw_attack = stats.attack
            if mine.has("rising_fury") and player["fury"]:
                raw_attack = int(raw_attack * (1 + min(20, player["fury"]) / 100))
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

            special_proc = offensive_mult > 1.0
            if offensive_mult != 1.0:
                raw_attack = int(raw_attack * offensive_mult)

            mob_def = _mob_defense_now()
            if mine.armor_penetration_pct > 0:  # Léthal
                mob_def = int(mob_def * (1 - min(100.0, mine.armor_penetration_pct) / 100))
            damage, recoil = resolve_hit(raw_attack, mob_def)

            title_bonus = title_bonuses_by_player.get(player["player_id"])
            if title_bonus is not None and mob_family:
                damage = max(1, round(damage * title_bonus.damage_multiplier_vs(mob_family)))

            elem_mult = elemental_mult_by_player.get(player["player_id"], 1.0)
            if elem_mult != 1.0:
                damage = max(1, round(damage * elem_mult))

            aura = _aura_pct()
            if aura:  # Soigneur dans l'équipe
                damage = max(1, round(damage * (1 + aura / 100)))
            if mine.damage_dealt_pct:  # Titan
                damage = max(1, round(damage * (1 + mine.damage_dealt_pct / 100)))
            if mine.has("elemental_power") and elem_mult > 1.0:
                damage = max(1, round(damage * 1.10))
            if mine.has("executioner") and mob_hp < mob_max_hp * 0.5:
                damage = max(1, round(damage * 1.20))
            if mine.has("boss_slayer") and mob_is_boss:
                damage = max(1, round(damage * 1.15))
            if player["shadow"]:  # Pas de l'ombre : prochaine action +10 %
                damage = max(1, round(damage * 1.10))
                player["shadow"] = False
            # NB : AOE (splash_damage_pct) — sans effet tant que les
            # combats n'opposent qu'un seul monstre.

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
            if landed and mine.has("rising_fury"):
                player["fury"] += 1

            action_text = f"{prefix}{player['name']} inflige {damage} dégâts"
            if crit and damage > 0:
                action_text += " (CRIT)"
            if special_proc and damage > 0:
                action_text += " ✨SPÉCIAL"
            if immune:
                action_text = f"{player['name']} : coup ignoré (immunité)"
            elif landed and mob_shield > 0:
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

            # Vaillant : le dernier l'emporte. Seulement s'il y a un allié à
            # protéger et qu'il ne provoque pas déjà (sinon le mana part pour rien).
            if (mine.taunt_chance_pct > 0 and taunter_id != player["player_id"] and _has_allies(player)
                    and random.random() < mine.taunt_chance_pct / 100 and self._spend(player, "taunt")):
                taunter_id = player["player_id"]
                action_text += " 🫀 provoque"

            if boss_reflect_pct > 0 and actual_damage > 0:
                reflected = max(1, round(actual_damage * boss_reflect_pct / 100))
                self._apply_player_damage(player, reflected, use_shield=False)
                action_text += f" (renvoi {reflected})"

            # Contrecoup : la DEF du monstre en trop revient au joueur (coup
            # arrivé sur l'armure, immunité comprise ; pas sur une esquive).
            if recoil > 0 and (landed or immune):
                taken = self._apply_player_damage(player, recoil, use_shield=False)
                action_text += f" (🔁 {taken} en contrecoup" + (" 💀)" if player["hp"] <= 0 else ")")

            action_text += _dry_note(player)
            turn_logs.append(snap(mob_action_text, players=[action_text]))
            _check_mob_thresholds()


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
                contributions[p["player_id"]].damage_tanked += pz["dmg"]
                lines.append(f"☠️ Poison : {p['name']} −{pz['dmg']}")
                pz["turns"] -= 1
                if pz["turns"] <= 0:
                    p["poison"] = None
            if p["bleeds"] and p["hp"] > 0:
                total = sum(b["dmg"] for b in p["bleeds"])
                self._apply_player_damage(p, total, use_shield=False)
                contributions[p["player_id"]].damage_tanked += total
                lines.append(f"🩸 Saignement : {p['name']} −{total}")
                for b in p["bleeds"]:
                    b["turns"] -= 1
                p["bleeds"] = [b for b in p["bleeds"] if b["turns"] > 0]
            if lines:
                turn_logs.append(snap(" · ".join(lines) + (" 💀" if p["hp"] <= 0 else "")))

        while mob_hp > 0 and _party_alive():
            round_count += 1
            if ((max_turns and turns >= max_turns) or (max_ticks and round_count > max_ticks)
                    or turns >= HARD_MAX_TURNS):
                break
            _escalate()

            for player in alive_party:
                if player["hp"] > 0 and not player["absorbed"]:
                    fill = player["stats"].speed
                    if player["slow"] > 0:
                        fill = max(1, fill // 2)   # ralenti (momie) : jauge à 50%
                    player["gauge"] += fill

            mob_gauge += mob.speed
            acted = False

            for player in alive_party:
                while (player["gauge"] >= 100 and player["hp"] > 0 and mob_hp > 0
                       and turns < HARD_MAX_TURNS):
                    _tick_dots(player)
                    if player["hp"] <= 0:
                        break
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
                    if player["slow"] > 0:
                        player["slow"] -= 1

                    # Charme : les non-charmés doivent d'abord abattre le charmé.
                    if _charmed_alive():
                        victim = _charmed_member()
                        dmg, crit, dodged, recoil = self._pvp_hit(player, victim, contributions)
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
                            turn_logs.append(snap(f"{mob.name} observe.", players=[
                                f"💚 {player['name']} {who} : +{healed} PV "
                                f"(💧 {player['mana']}/{player['mana_max']})"]))
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

                    _strike(player, offensive_mult)
                    # Coup double : 10 % de chance d'attaquer une 2e fois (jamais en chaîne).
                    if (mine.has("double_strike") and mob_hp > 0 and random.random() < 0.10
                            and self._spend(player, "double_strike")):
                        _strike(player, prefix="⚡ Coup double — ")

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

                    if mob_hp <= 0:
                        break

            # ── Tour du mob ──
            if _charmed_alive():
                mob_gauge = 0  # succube protégée, passive tant que le charmé vit
            _escalate()
            boss_actions = 0
            # Garde-fou HARD_MAX_TURNS aussi ICI : l'escalade multiplie la
            # vitesse du monstre, qui pourrait sinon agir des millions de fois
            # dans un seul tick.
            while (mob_gauge >= 100 and mob_hp > 0 and _party_alive() and not _charmed_alive()
                   and turns < HARD_MAX_TURNS):
                turns += 1
                acted = True
                mob_gauge -= 100
                boss_actions += 1

                # Chaman : soin d'urgence (remplace l'attaque de ce tour).
                if chaman_pending:
                    chaman_pending = False
                    if anti_heal:
                        mob_hp += (mob_max_hp - mob_hp) // 2
                        turn_logs.append(snap(f"✨ {mob.name} canalise… le soin est entravé (Anti-soin) !"))
                    else:
                        mob_hp = mob_max_hp
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
                    if not pool or mob_hp <= 0:   # un contrecoup a pu l'achever
                        break
                    targets = pool if aoe else [_single_target(pool)]
                    parts = []
                    for target in targets:
                        dmg, mob_crit, dodged = self._resolve_mob_hit(
                            mob, target, contributions, title_bonuses_by_player,
                            incoming_elemental_mult_by_player, mob_family,
                            extra_multiplier=single_mult, attack_override=atk_now,
                            is_aoe=aoe)
                        # Vol de vie (gargouille) — divisé par deux par Anti-soin
                        if not dodged and dmg > 0 and "lifesteal" in ab:
                            heal = round(dmg * ab["lifesteal"].get("pct", 0) / 100)
                            if anti_heal:
                                heal //= 2
                            if heal > 0:
                                mob_hp = min(mob_max_hp, mob_hp + heal)
                        # Contrecoup (Épines compris) : la DEF en trop frappe le monstre.
                        _recoil_to_mob(target)
                        # Riposte : 10 % de chance de contre-attaquer (jamais en chaîne).
                        if (not dodged and target["hp"] > 0 and mob_hp > 0
                                and P(target).has("counter_attack") and random.random() < 0.10
                                and self._spend(target, "counter_attack")):
                            _strike(target, prefix="↩️ Riposte — ")
                        # Étourdissement (gobelin géant / banshee) — non cumulable
                        stunned_now = False
                        if not dodged and "stun" in ab and not target["stunned"]:
                            if random.random() < ab["stun"].get("chance", 0) / 100:
                                target["stunned"] = True
                                stunned_now = True
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
                            mob_shield = mob_max_hp
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
                            tag += _tags(target)
                            parts.append(f"{target['name']} −{dmg}{tag}")
                    verb = "déchaîne une frappe de zone" if aoe else "frappe"
                    heal_tag = " (vol de vie)" if "lifesteal" in ab else ""
                    turn_logs.append(snap(f"{mob.name} {verb}{heal_tag} : " + " · ".join(parts)))
                    if not _party_alive():
                        break

                # Réaction en chaîne (gobelin ballon) : chaque salve peut se répliquer.
                if "chain_replicate" in ab and _party_alive():
                    chance = ab["chain_replicate"].get("chance", 20) / 100
                    rep = 0
                    while _party_alive() and random.random() < chance and rep < 15:
                        rep += 1
                        pool = _mob_targets()
                        if not pool:
                            break
                        rtargets = pool if aoe else [_single_target(pool)]
                        parts = []
                        for target in rtargets:
                            dmg, mob_crit, dodged = self._resolve_mob_hit(
                                mob, target, contributions, title_bonuses_by_player,
                                incoming_elemental_mult_by_player, mob_family,
                                extra_multiplier=single_mult, attack_override=atk_now,
                                is_aoe=aoe)
                            _recoil_to_mob(target)
                            parts.append(f"{target['name']} esquive" if dodged
                                         else f"{target['name']} −{dmg}"
                                         + (" 💀" if target["hp"] <= 0 else "")
                                         + _tags(target))
                        turns += 1
                        turn_logs.append(snap(f"💥 Réaction en chaîne (réplique {rep}) : "
                                              + " · ".join(parts)))

                # La provocation ne vaut que pour la PROCHAINE attaque.
                taunter_id = None
                if not _party_alive():
                    break

            # Effets « à chaque tour du boss » — world boss : un passage par
            # action du boss pendant ce tick (pas un par tick).
            for _ in range(boss_actions):
                boss_turn_count += 1
                if mob_hp <= 0 or not _party_alive():
                    break
                # Invocations (adds) : une de plus tous les `summon_turn_interval`
                # tours du boss, chacune frappe un joueur au hasard.
                if adds_attack > 0 and adds_interval > 0 and adds_max > 0:
                    if boss_turn_count % adds_interval == 0 and active_adds < adds_max:
                        active_adds += 1
                    for _ in range(active_adds):
                        alive = [p for p in alive_party if p["hp"] > 0]
                        if not alive:
                            break
                        victim = random.choice(alive)
                        # Même formule ; pas de contrecoup : une invocation
                        # n'a pas de PV à elle.
                        add_dmg, _ = resolve_hit(adds_attack, victim["stats"].defense)
                        self._apply_player_damage(victim, add_dmg)
                        contributions[victim["player_id"]].damage_tanked += adds_attack
                # Régénération (monstres des zones hautes) : % des PV max par action.
                if "regen" in ab and mob_hp < mob_max_hp:
                    heal = round(mob_max_hp * ab["regen"].get("pct", 3) / 100)
                    heal = heal // 2 if anti_heal else heal
                    mob_hp = min(mob_max_hp, mob_hp + heal)
                # Auto-soin du boss.
                if boss_heal_per_turn > 0:
                    heal = boss_heal_per_turn // 2 if anti_heal else boss_heal_per_turn
                    mob_hp = min(mob_max_hp, mob_hp + heal)

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
                        extra_multiplier=mult, is_aoe=True)
                    target.pop("_recoil", None)  # le monstre est déjà mort
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
            contribution.mana_max = member["mana_max"]
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
        attack_override: int | None = None, is_aoe: bool = False,
    ) -> tuple[int, bool, bool]:
        """Coup du mob sur un joueur (`damage_formula` : crit AVANT défense,
        puis bouclier, puis PV). `attack_override` = attaque effective
        (furie/résurrection). Renvoie (dégâts, crit, esquivé) ; le contrecoup
        éventuel est posé dans `target["_recoil"]`, à appliquer au monstre par
        l'appelant."""
        tstats: Stats = target["stats"]
        gear = self._p(target)

        if can_dodge and tstats.dodge > 0 and random.random() < (tstats.dodge / 100):
            contributions[target["player_id"]].dodges += 1
            if gear.has("shadow_step"):
                target["shadow"] = True
                target["shadow_guard"] = True
            return 0, False, True

        # Garde de l'exil : la première attaque reçue est annulée.
        if gear.has("first_hit_ward") and not target.get("warded"):
            target["warded"] = True
            if self._spend(target, "first_hit_ward"):
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
                contributions[guard["player_id"]].damage_tanked += portion
                target["_redirected"] = (guard["name"], taken)

        dealt = self._apply_player_damage(target, mob_damage)
        contributions[target["player_id"]].damage_tanked += raw_attack
        return dealt, crit, False

    # ------------------------------------------------------------ passifs
    def _p(self, member) -> CombatPassives:
        return getattr(self, "_passives", {}).get(member["player_id"], NO_PASSIVES)

    def _spend(self, member, ability: str) -> bool:
        """Prélève le mana d'une compétence active (cf. MANA_COSTS). Faux si
        la réserve ne suffit pas : l'effet n'a pas lieu."""
        cost = getattr(self, "_mana_costs", MANA_COSTS).get(ability, 0)
        contrib = getattr(self, "_contribs", {}).get(member["player_id"])
        if member.get("mana", 0) < cost:
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
        Renvoie les dégâts retirés aux PV (après bouclier), comme avant."""
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
            damage = member["hp"] - 1
        member["hp"] = max(0, member["hp"] - damage)
        # Revenant : la première mort ramène à 50 % des PV.
        if (member["hp"] <= 0 and self._p(member).has("undying") and not member.get("gear_revived")
                and self._spend(member, "undying")):
            member["gear_revived"] = True
            member["hp"] = max(1, member["max_hp"] // 2)
            member["_revived"] = True
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

    def _snapshot(self, turns, player_actions, mob_action, alive_party, mob, mob_hp,
                  mob_shield: int = 0, mob_max_hp: int | None = None) -> PartyBattleTurnLog:
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
                "max_hp": mob_max_hp if mob_max_hp is not None else mob.max_hp,
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
