"""Catalogue des passifs d'équipement — un passif par pièce, une pièce par passif.

Actifs à partir de l'ÉPIQUE (cf. `gear_service.PASSIVE_MIN_RARITY`), identiques
quelle que soit la rareté. Les effets sont appliqués par le moteur de combat
(`PartyCombatService`), l'économie par `EncounterService`.

Règles de cumul (décidées avec l'auteur) :
  • effets sur l'ENNEMI (ATK réduite, soins divisés…) : un seul exemplaire actif
    par combat, le plus fort — dix joueurs à −5 % d'ATK, ça reste −5 % ;
  • effets « UNE FOIS PAR COMBAT » (annuler la 1re attaque, ténacité,
    résurrection) : une fois par joueur et par combat, même si l'arbre de
    compétences donne le même effet ;
  • effets CROISSANTS en combat : plafonnés ;
  • pas de RÉACTION EN CHAÎNE : une contre-attaque ou une double attaque ne
    déclenche jamais un autre de ces effets ;
  • ÉCONOMIE (or, XP, drop, essences) : personnelle, seulement sur les monstres
    (rien à gagner en épreuve de rang ni en défi).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GearPassive:
    code: str
    name: str
    description: str
    #: Catégorie : "offense", "defense", "support", "enemy" (effet sur l'ennemi,
    #: non cumulable), "economy" (butin des monstres uniquement).
    kind: str

    @property
    def full_description(self) -> str:
        """Description + coût en mana s'il s'agit d'une compétence active."""
        from app.domain.services.combat_passives import mana_cost_text

        cost = mana_cost_text(self.code)
        return f"{self.description} ({cost})" if cost else self.description


PASSIVES: dict[str, GearPassive] = {p.code: p for p in (
    GearPassive("first_strike_crit", "Frappe d'ouverture",
                "Ta première attaque est forcément critique ; si elle l'était déjà, "
                "c'est un super-critique (les deux critiques se cumulent).", "offense"),
    GearPassive("armor_pierce", "Perce-armure",
                "Tes coups ignorent 15 % de la défense ennemie.", "offense"),
    GearPassive("healing_hands", "Mains guérisseuses",
                "Tes soins donnés sont augmentés de 10 %, et 10 % des soins que tu "
                "donnes à un allié frappent aussi l'ennemi.", "support"),
    GearPassive("executioner", "Exécuteur",
                "+20 % de dégâts contre un ennemi sous 50 % de ses PV.", "offense"),
    GearPassive("double_strike", "Coup double",
                "10 % de chance d'attaquer deux fois d'affilée.", "offense"),
    GearPassive("boss_slayer", "Tueur de boss",
                "+15 % de dégâts contre les boss.", "offense"),
    GearPassive("rising_fury", "Fureur montante",
                "Chaque attaque augmente ton attaque de 1 % pour le combat (max +20 %).", "offense"),
    GearPassive("thorns", "Épines",
                "Ton contrecoup est augmenté de 10 % (la défense qui dépasse 75 % de "
                "l'attaque adverse revient à l'attaquant en dégâts).", "defense"),
    GearPassive("stone_skin", "Peau de pierre",
                "Chaque coup subi augmente ta défense de 1 % pour le combat (max +20 %).", "defense"),
    GearPassive("counter_attack", "Riposte",
                "10 % de chance de contre-attaquer à chaque coup subi.", "defense"),
    GearPassive("undying", "Revenant",
                "La première fois que tu meurs, tu reviens à la vie avec 50 % de tes PV.", "defense"),
    GearPassive("crit_ward", "Bandelettes protectrices",
                "Les dégâts critiques que tu reçois sont réduits de 25 %.", "defense"),
    GearPassive("shadow_step", "Pas de l'ombre",
                "Après une esquive : ta prochaine action fait 10 % de plus, et le "
                "prochain coup que tu reçois 10 % de moins.", "defense"),
    GearPassive("first_hit_ward", "Garde de l'exil",
                "La première attaque que tu reçois est annulée.", "defense"),
    GearPassive("anti_heal", "Anti-soin",
                "Les soins de l'ennemi sont divisés par deux.", "enemy"),
    GearPassive("taunt_guard", "Défi",
                "Tu commences le combat en provocation, et tu subis 15 % de dégâts "
                "en moins tant qu'elle dure.", "defense"),
    GearPassive("weakening_cry", "Cri affaiblissant",
                "L'attaque de l'ennemi est réduite de 5 %.", "enemy"),
    GearPassive("lucky_find", "Trouvaille",
                "Tes chances de butin d'équipement sont augmentées de 10 % "
                "(1 % devient 1,1 %), pour les raretés INFÉRIEURES à celle de "
                "cette pièce — jamais pour le mythique.", "economy"),
    GearPassive("blast_ward", "Pare-souffle",
                "Les dégâts de zone que tu reçois sont réduits de 50 %.", "defense"),
    GearPassive("elemental_power", "Puissance élémentaire",
                "Tes dégâts élémentaires sont augmentés de 10 %.", "offense"),
    GearPassive("essence_hunter", "Chasseur d'essences",
                "Chaque monstre tué te donne 1 essence de plus de son élément.", "economy"),
    GearPassive("tenacity", "Ténacité",
                "Le premier coup mortel que tu reçois te laisse à 1 PV.", "defense"),
    GearPassive("iron_will", "Volonté de fer",
                "Tu es immunisé au charme.", "defense"),
    # --- Zones C → S (27/10/2026, validés avec l'auteur) : plus le monstre est
    # fort, plus son passif reprend SA mécanique ; l'élite a une signature.
    # Sanctuaire primordial (C)
    GearPassive("pack_instinct", "Instinct de meute",
                "+3 % de dégâts par allié encore debout (max +9 %).", "offense"),
    GearPassive("kind_antlers", "Ramure bienveillante",
                "Tout le groupe reçoit 15 % de soins en plus (une seule ramure par groupe).", "support"),
    GearPassive("root_venom", "Sève vénéneuse",
                "Tes coups empoisonnent l'ennemi : 1 % de ses PV max à chacune de ses "
                "actions pendant 3 actions, au plus 25 % de ton attaque (non cumulable).", "enemy"),
    GearPassive("crushing_paw", "Coup de patte brisant",
                "Chaque coup réduit la défense de l'ennemi de 3 % pour le combat (max −15 %, "
                "non cumulable).", "enemy"),
    GearPassive("verdant_moss", "Mousse vivace",
                "La première fois que tu passes sous 30 % de PV, tu récupères 10 % de tes "
                "PV max à chacune de tes 7 actions suivantes.", "defense"),
    GearPassive("storm_eye", "Œil de la tempête",
                "Ta première action frappe TOUS les ennemis, avec 50 % de chance d'étourdir "
                "chacun (pas les boss).", "offense"),
    # Éclipse éternelle (B)
    GearPassive("night_flight", "Vol nocturne",
                "+5 % d'esquive tant que tu es au-dessus de 50 % de tes PV.", "defense"),
    GearPassive("flesh_feast", "Festin de chair",
                "Chaque ennemi vaincu te rend 25 % de tes PV max.", "defense"),
    GearPassive("lunar_rage", "Rage lunaire",
                "Sous 50 % de PV : +15 % d'attaque et de vitesse.", "offense"),
    GearPassive("blood_pact", "Pacte de sang",
                "À court de mana, tes compétences se paient en PV : 5 % de tes PV max, et "
                "l'érosion réduit tes PV max de 5 % pour le reste du combat.", "support"),
    GearPassive("eclipse_mirror", "Miroir d'éclipse",
                "15 % des dégâts que tu reçois sont renvoyés à l'attaquant.", "defense"),
    GearPassive("scarlet_thirst", "Soif écarlate",
                "Tes coups critiques te soignent de 20 % des dégâts infligés.", "offense"),
    GearPassive("bloody_waltz", "Valse sanglante",
                "Après chaque esquive, ton coup suivant est un critique qui fait saigner "
                "(10 % des dégâts à chaque action de l'ennemi, 3 actions, jusqu'à 3 fois).", "offense"),
    # Cimes des Wyrms (A)
    GearPassive("ambush", "Embuscade",
                "+25 % de dégâts contre un ennemi qui n'a pas encore agi.", "offense"),
    GearPassive("young_breath", "Souffle juvénile",
                "Toutes les 5 attaques, des flammes frappent tous les ennemis (30 % de ton "
                "attaque, sans défense).", "offense"),
    GearPassive("lingering_ember", "Braise persistante",
                "Tes critiques enflamment l'ennemi : −20 % d'attaque pendant 2 actions (non "
                "cumulable) et 10 % des dégâts du coup à chacune de ses 2 actions suivantes "
                "(cumulable).", "enemy"),
    GearPassive("dive", "Piqué",
                "Ta première attaque frappe 3 fois, à 60 % chacune.", "offense"),
    GearPassive("frost_bite", "Morsure du givre",
                "15 % de chance de geler l'ennemi qui te frappe : il perd sa prochaine action "
                "(pas les boss).", "defense"),
    GearPassive("guardian_oath", "Serment du gardien",
                "Tant que tu provoques : −20 % de dégâts reçus pour toi, −10 % pour tes alliés.", "defense"),
    GearPassive("ancestral_breath", "Souffle ancestral",
                "Exécute la cible de ton attaque si elle passe sous 20 % de ses PV (les boss "
                "y sont immunisés).", "offense"),
    # Faille du Néant (S)
    GearPassive("abyssal_reserve", "Réserve abyssale",
                "Tes compétences coûtent 20 % de mana en moins.", "support"),
    GearPassive("void_gaze", "Regard du vide",
                "L'ennemi ne peut pas esquiver tes coups.", "offense"),
    GearPassive("devour", "Dévoration",
                "Quand un allié meurt, tu gagnes 10 % de son attaque, de sa défense et de ses "
                "PV max pour le reste du combat.", "offense"),
    GearPassive("void_echo", "Échos du vide",
                "Toutes les 8 actions, un écho frappe la cible (50 % de ton attaque, sans "
                "défense) et absorbe le prochain coup que tu reçois.", "offense"),
    GearPassive("astral_grip", "Étreinte astrale",
                "Tes coups ralentissent l'ennemi de 5 % (max −25 %, non cumulable).", "enemy"),
    GearPassive("broken_grace", "Grâce brisée",
                "Le premier allié qui tombe se relève avec 30 % de ses PV (une fois par combat).", "support"),
    GearPassive("devouring_void", "Néant dévorant",
                "Un coup sur deux ignore 50 % de la défense ennemie.", "offense"),
)}


def get_passive(code: str | None) -> GearPassive | None:
    return PASSIVES.get(code or "")


def active_passives(equipped_items) -> set[str]:
    """Codes des passifs ACTIFS d'un équipement porté (pièces épiques et plus).

    `equipped_items` : PlayerEquipmentItem (ou tout objet avec `rarity` et
    `item_definition.passive`)."""
    from app.domain.services.gear_service import passive_active

    return {
        item.item_definition.passive
        for item in equipped_items or []
        if getattr(item.item_definition, "passive", "")
        and passive_active(getattr(item, "rarity", "common") or "common")
    }
