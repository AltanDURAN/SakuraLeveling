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
