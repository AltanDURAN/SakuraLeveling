"""Types d'événements du journal et sources d'or.

Chaque mouvement d'or passe par `PlayerRepository.add_gold(..., source=)` :
le journal est complet PAR CONSTRUCTION, et un appel qui oublie sa source
apparaît en « autre » dans l'économie (à corriger, pas à deviner).
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------- événements
INTERACTION = "interaction"   # ref = commande (« boss moi ») ou bouton
COMBAT = "combat"             # un par participant ; zone = salon, ref = monstre chef
FLEE = "flee"                 # monstres repartis sans combattant : COMPTEUR par heure et par zone (qty)
GOLD = "gold"                 # ref = source, gold = variation RÉELLE du solde
LEVEL_UP = "level_up"         # qty = nouveau niveau, data.from
GEAR_DROP = "gear_drop"       # ref = pièce, data.rarity
SHOP_BUY = "shop_buy"         # ref = objet, qty, gold = −prix
FUSION = "fusion"             # ref = pièce, data.from → data.to
BREW = "brew"                 # ref = potion, qty
CONSUMABLE = "consumable"     # ref = objet utilisé
QUEST = "quest"               # ref = daily|weekly, qty = quêtes réclamées
DAILY = "daily"               # qty = série
RANK_TRIAL = "rank_trial"     # ref = rang visé, data.role/score/passed
RANK_UP = "rank_up"           # ref = nouveau rang, qty = niveau
TOWER = "tower"               # qty = étage, data.won
ROLE_TRIAL = "role_trial"     # ref = rôle, qty = score
BOSS_FIGHT = "boss_fight"     # ref = boss, data.dmg/tank/heal
MARKET_SALE = "market_sale"   # ref = objet, gold = prix, data.seller/fee
TRANSFER = "transfer"         # gold = montant, data.to
OFFERING = "offering"         # gold = don
SEER = "seer"                 # ref = élément lu
RESPEC = "respec"             # ref = stats|arbre
TUTORIAL = "tutorial"         # ref = passe|termine
MEMBER_JOIN = "member_join"   # discord_id
RULES = "rules"               # discord_id, qty = version du règlement acceptée
ERROR = "error"               # ref = commande en erreur
SEASON_START = "season"       # qty = numéro de la saison (reset de saison : le journal repart de là)
BOOSTER = "booster"           # qty = boosters ouverts, gold = −prix, data.best/new/brillantes/free
CARD_RECYCLE = "card_recycle" # qty = cartes recyclées, data.petals
CARD_CRAFT = "card_craft"     # ref = carte fabriquée, data.petals
SEASONAL = "seasonal"         # ref = advent:<case> | christmas | shop:<boutique>:<objet>

#: Ce qui compte comme « le joueur joue » (temps de jeu, heures actives).
ACTIVITY_KINDS = frozenset({
    INTERACTION, COMBAT, SHOP_BUY, FUSION, BREW, CONSUMABLE, QUEST, DAILY,
    RANK_TRIAL, TOWER, ROLE_TRIAL, BOSS_FIGHT, MARKET_SALE, TRANSFER, OFFERING, SEER,
    BOOSTER, CARD_RECYCLE, CARD_CRAFT, SEASONAL,
})

# --------------------------------------------------------------- sources d'or
CREATION = "creation"
DESTRUCTION = "destruction"
TRANSFER_FLOW = "transfer"
ADMIN = "admin"
OTHER = "other"


@dataclass(frozen=True)
class GoldSource:
    code: str
    label: str
    emoji: str
    #: creation / destruction / transfer / admin / other ; "" = selon le signe
    #: (un événement peut donner ou prendre de l'or).
    flow: str = ""


GOLD_SOURCES: dict[str, GoldSource] = {s.code: s for s in (
    GoldSource("combat", "Combats", "⚔️", CREATION),
    GoldSource("quete", "Quêtes", "📜", CREATION),
    GoldSource("daily", "Solde /daily", "📅", CREATION),
    GoldSource("raid", "Raid", "🐉", CREATION),
    GoldSource("tour", "Tour", "🗼", CREATION),
    GoldSource("defi", "Défis", "🎯", CREATION),
    GoldSource("evenement", "Événements", "🎲"),
    GoldSource("boutique", "Sorn (boutique)", "🏪", DESTRUCTION),
    GoldSource("cartes", "Boosters de cartes", "🎴", DESTRUCTION),
    GoldSource("fusion", "Fusion (Borak)", "⚒️", DESTRUCTION),
    GoldSource("alchimie", "Potions (Elna)", "⚗️", DESTRUCTION),
    GoldSource("voyante", "Voyante", "🔮", DESTRUCTION),
    GoldSource("offrande", "Offrande", "🙏", DESTRUCTION),
    GoldSource("brocante", "Brocante", "🏷️", TRANSFER_FLOW),
    GoldSource("echange", "Échanges", "🤝", TRANSFER_FLOW),
    GoldSource("virement", "Virements", "💸", TRANSFER_FLOW),
    GoldSource("admin", "Admin", "🛠️", ADMIN),
    GoldSource("autre", "Non étiqueté", "❔", OTHER),
)}

#: Ordre FIXE des sources dans les graphiques (la couleur suit la source).
CREATION_ORDER = ("combat", "quete", "daily", "raid", "tour", "defi", "evenement")
DESTRUCTION_ORDER = ("boutique", "cartes", "fusion", "alchimie", "voyante", "offrande", "taxe", "evenement")


def gold_source(code: str | None) -> GoldSource:
    return GOLD_SOURCES.get(code or "autre", GoldSource(code or "autre", code or "autre", "❔", OTHER))


def flow_of(source: str | None, delta: int) -> str:
    """Création, destruction, transfert entre joueurs, admin ou non étiqueté."""
    s = gold_source(source)
    if s.flow:
        return s.flow
    return CREATION if delta >= 0 else DESTRUCTION


# ------------------------------------------------------------------- rangs
RANK_ORDER = ("F", "E", "D", "C", "B", "A", "S", "SS", "SSS")
