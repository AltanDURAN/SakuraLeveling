from enum import Enum, StrEnum


class EquipmentSlot(StrEnum):
    """Les 7 emplacements d'équipement PHYSIQUES d'un joueur.

    Système simplifié : on ne distingue plus main droite / main gauche ni les
    pièces d'armure une par une. Un item déclare un TYPE (`ItemSlotType`) et
    peut aller dans n'importe quel emplacement de ce type.
    """

    TETE = "tete"
    CORPS = "corps"
    ACCESSOIRE_1 = "accessoire_1"
    ACCESSOIRE_2 = "accessoire_2"
    ACCESSOIRE_3 = "accessoire_3"
    ARME_1 = "arme_1"
    ARME_2 = "arme_2"


class ItemSlotType(StrEnum):
    """Ce qu'un ITEM déclare : la FAMILLE d'emplacements où il peut aller.

    Un accessoire ne vise pas « accessoire_2 » mais « accessoire » — le use
    case d'équipement choisit ensuite l'emplacement libre.
    """

    TETE = "tete"
    CORPS = "corps"
    ACCESSOIRE = "accessoire"
    ARME = "arme"          # armes ET boucliers : ils partagent les 2 mains


ACCESSORY_SLOTS: list[EquipmentSlot] = [
    EquipmentSlot.ACCESSOIRE_1,
    EquipmentSlot.ACCESSOIRE_2,
    EquipmentSlot.ACCESSOIRE_3,
]

# Les 2 mains. Une arme/bouclier 1 main occupe UN emplacement (on peut donc en
# porter deux) ; une 2 mains occupe ARME_1 et verrouille ARME_2.
WEAPON_SLOTS: list[EquipmentSlot] = [
    EquipmentSlot.ARME_1,
    EquipmentSlot.ARME_2,
]

# Emplacements autorisés pour chaque type d'item.
SLOTS_FOR_ITEM_TYPE: dict[str, list[EquipmentSlot]] = {
    ItemSlotType.TETE.value: [EquipmentSlot.TETE],
    ItemSlotType.CORPS.value: [EquipmentSlot.CORPS],
    ItemSlotType.ACCESSOIRE.value: ACCESSORY_SLOTS,
    ItemSlotType.ARME.value: WEAPON_SLOTS,
}

# Emplacement → type d'item qui l'occupe (relation inverse).
ITEM_TYPE_FOR_SLOT: dict[str, str] = {
    slot.value: item_type
    for item_type, slots in SLOTS_FOR_ITEM_TYPE.items()
    for slot in slots
}

# Panoplies : SEULS ces emplacements comptent (les accessoires en sont exclus),
# d'où des paliers à 2 et 4 pièces.
PANOPLIE_SLOTS: list[EquipmentSlot] = [
    EquipmentSlot.TETE,
    EquipmentSlot.CORPS,
    EquipmentSlot.ARME_1,
    EquipmentSlot.ARME_2,
]
PANOPLIE_TIERS: tuple[int, ...] = (2, 4)

# Ordre canonique d'affichage.
SLOT_ORDER: list[str] = [
    EquipmentSlot.TETE.value,
    EquipmentSlot.CORPS.value,
    EquipmentSlot.ARME_1.value,
    EquipmentSlot.ARME_2.value,
    EquipmentSlot.ACCESSOIRE_1.value,
    EquipmentSlot.ACCESSOIRE_2.value,
    EquipmentSlot.ACCESSOIRE_3.value,
]


SLOT_ICONS: dict[str, str] = {
    EquipmentSlot.TETE.value:         "⛑️",
    EquipmentSlot.CORPS.value:        "👕",
    EquipmentSlot.ARME_1.value:       "⚔️",
    EquipmentSlot.ARME_2.value:       "🛡️",
    EquipmentSlot.ACCESSOIRE_1.value: "💍",
    EquipmentSlot.ACCESSOIRE_2.value: "📿",
    EquipmentSlot.ACCESSOIRE_3.value: "🎗️",
}


SLOT_LABELS: dict[str, str] = {
    EquipmentSlot.TETE.value:         "Tête",
    EquipmentSlot.CORPS.value:        "Corps",
    EquipmentSlot.ARME_1.value:       "Arme / Bouclier 1",
    EquipmentSlot.ARME_2.value:       "Arme / Bouclier 2",
    EquipmentSlot.ACCESSOIRE_1.value: "Accessoire 1",
    EquipmentSlot.ACCESSOIRE_2.value: "Accessoire 2",
    EquipmentSlot.ACCESSOIRE_3.value: "Accessoire 3",
}


# Mapping ItemCategory.value → emoji (cards d'items, autocomplete).
CATEGORY_ICONS: dict[str, str] = {
    "arme":       "⚔️",
    "bouclier":   "🛡️",
    "tete":       "⛑️",
    "corps":      "👕",
    "accessoire": "💍",
    "consumable": "🧪",
    "resource":   "🌾",
}


# Catégories d'items qui passent par la FORGE (métal : armes, boucliers,
# armures). Tout le reste (accessoires, tissus…) tombe dans /fabriquer.
FORGE_CATEGORIES: set[str] = {"arme", "bouclier", "tete", "corps"}


# Catégories d'items qui s'ÉQUIPENT (à opposer à resource / consumable). Source
# unique de vérité : /inventaire les exclut, /equipement_liste les affiche.
EQUIPABLE_CATEGORIES: frozenset[str] = frozenset(
    {"arme", "bouclier", "tete", "corps", "accessoire"}
)


class ItemCategory(StrEnum):
    """Catégories simplifiées : une par type d'emplacement, plus les
    non-équipables. Armes et boucliers restent distincts (la forge et le
    gameplay les différencient) mais partagent les MÊMES emplacements."""

    RESOURCE = "resource"
    CONSUMABLE = "consumable"
    ARME = "arme"
    BOUCLIER = "bouclier"
    TETE = "tete"
    CORPS = "corps"
    ACCESSOIRE = "accessoire"


class ItemRarity(str, Enum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"


# Libellés FR + icônes des catégories / raretés (affichage admin et bot).
ITEM_CATEGORY_LABELS: dict[str, str] = {
    "resource": "Ressource", "consumable": "Consommable", "potion": "Potion",
    "arme": "Arme", "bouclier": "Bouclier",
    "tete": "Tête", "corps": "Corps", "accessoire": "Accessoire",
}
ITEM_CATEGORY_EMOJIS: dict[str, str] = {
    "resource": "🪵", "consumable": "🧪", "potion": "🧪",
    "arme": "⚔️", "bouclier": "🛡️",
    "tete": "⛑️", "corps": "👕", "accessoire": "💍",
}
ITEM_RARITY_LABELS: dict[str, str] = {
    "common": "Commun", "uncommon": "Peu commun", "rare": "Rare",
    "epic": "Épique", "legendary": "Légendaire",
}

EQUIPMENT_SLOT_LABELS: dict[str, str] = {
    **SLOT_LABELS,
    # Types déclarés par les items (l'admin édite ceux-là).
    ItemSlotType.TETE.value: "Tête",
    ItemSlotType.CORPS.value: "Corps",
    ItemSlotType.ACCESSOIRE.value: "Accessoire",
    ItemSlotType.ARME.value: "Arme / Bouclier",
}

# Libellés COURTS pour les rendus contraints en largeur (cartes de /equipement,
# 4 colonnes) : « Arme / Bouclier 1 » débordait de sa carte.
SLOT_LABELS_SHORT: dict[str, str] = {
    EquipmentSlot.TETE.value:         "Tête",
    EquipmentSlot.CORPS.value:        "Corps",
    EquipmentSlot.ARME_1.value:       "Arme 1",
    EquipmentSlot.ARME_2.value:       "Arme 2",
    EquipmentSlot.ACCESSOIRE_1.value: "Access. 1",
    EquipmentSlot.ACCESSOIRE_2.value: "Access. 2",
    EquipmentSlot.ACCESSOIRE_3.value: "Access. 3",
}

# TYPE d'emplacement déduit de la catégorie de l'item (None = non équipable).
# Armes ET boucliers pointent vers "arme" : ils se disputent les deux mains.
ITEM_CATEGORY_DEFAULT_SLOT: dict[str, str | None] = {
    "arme": ItemSlotType.ARME.value,
    "bouclier": ItemSlotType.ARME.value,
    "tete": ItemSlotType.TETE.value,
    "corps": ItemSlotType.CORPS.value,
    "accessoire": ItemSlotType.ACCESSOIRE.value,
    "resource": None, "consumable": None, "potion": None,
}

# Correspondance ANCIEN système → NOUVEAU (migration du contenu existant).
LEGACY_CATEGORY_MAP: dict[str, str] = {
    "weapon": "arme", "shield": "bouclier",
    "helmet": "tete",
    "chest": "corps", "legs": "corps", "boots": "corps",
    "necklace": "accessoire", "bracelet": "accessoire", "ring": "accessoire",
    "belt": "accessoire", "cape": "accessoire", "earring": "accessoire",
}
LEGACY_SLOT_MAP: dict[str, str] = {
    "casque": ItemSlotType.TETE.value,
    "plastron": ItemSlotType.CORPS.value,
    "jambieres": ItemSlotType.CORPS.value,
    "bottes": ItemSlotType.CORPS.value,
    "main_droite": ItemSlotType.ARME.value,
    "main_gauche": ItemSlotType.ARME.value,
    "collier": ItemSlotType.ACCESSOIRE.value,
    "bracelet": ItemSlotType.ACCESSOIRE.value,
    "bague": ItemSlotType.ACCESSOIRE.value,
    "ceinture": ItemSlotType.ACCESSOIRE.value,
    "cape": ItemSlotType.ACCESSOIRE.value,
    "boucle_oreille": ItemSlotType.ACCESSOIRE.value,
}


# Stat de bonus d'item : libellé FR + icône (affichage admin).
STAT_LABELS: dict[str, str] = {
    "max_hp": "PV", "attack": "Attaque", "defense": "Défense", "speed": "Vitesse",
    "crit_chance": "Crit %", "crit_damage": "Crit dmg", "dodge": "Esquive %",
    "hp_regeneration": "Régén PV",
    "mana_max": "Mana max", "mana_regeneration": "Régén mana",
}
# SOURCE UNIQUE des emojis de stats (bot ET admin). Les symboles historiques
# du bot font foi — 🌀 = esquive partout, donc le mana prend 🔷 / 💧.
STAT_EMOJIS: dict[str, str] = {
    "max_hp": "❤️", "attack": "⚔️", "defense": "🛡️", "speed": "💨",
    "crit_chance": "🎯", "crit_damage": "💥", "dodge": "🌀",
    "hp_regeneration": "✨",
    "mana_max": "🔷", "mana_regeneration": "💧",
}


class CooldownAction(StrEnum):
    DAILY = "daily"


class Element(StrEnum):
    """Éléments du jeu (système élémentaire V1).

    Mono-élément en V1 (un boss/joueur attaque avec un seul élément à la fois) ;
    le double/triple élément (rare) est prévu plus tard sans changer cet enum.

    Tiers de complexité (purement informatif, pour le contenu) :
    - basiques : eau / feu / plante
    - intermédiaires : glace / vent / terre
    - avancés : tenebre / lumiere
    """

    EAU = "eau"
    FEU = "feu"
    PLANTE = "plante"
    GLACE = "glace"
    VENT = "vent"
    TERRE = "terre"
    TENEBRE = "tenebre"
    LUMIERE = "lumiere"


# Ordre canonique d'affichage (basiques → intermédiaires → avancés).
ALL_ELEMENTS: list[Element] = [
    Element.EAU,
    Element.FEU,
    Element.PLANTE,
    Element.GLACE,
    Element.VENT,
    Element.TERRE,
    Element.TENEBRE,
    Element.LUMIERE,
]

ELEMENT_EMOJIS: dict[str, str] = {
    Element.EAU.value:     "💧",
    Element.FEU.value:     "🔥",
    Element.PLANTE.value:  "🌿",
    Element.GLACE.value:   "❄️",
    Element.VENT.value:    "🌪️",
    Element.TERRE.value:   "⛰️",
    Element.TENEBRE.value: "🌑",
    Element.LUMIERE.value: "☀️",
}

ELEMENT_LABELS: dict[str, str] = {
    Element.EAU.value:     "Eau",
    Element.FEU.value:     "Feu",
    Element.PLANTE.value:  "Plante",
    Element.GLACE.value:   "Glace",
    Element.VENT.value:    "Vent",
    Element.TERRE.value:   "Terre",
    Element.TENEBRE.value: "Ténèbre",
    Element.LUMIERE.value: "Lumière",
}

_VALID_ELEMENTS: set[str] = {e.value for e in ALL_ELEMENTS}


def parse_elements(raw: str | None) -> list[str]:
    """Parse le champ `element` d'un mob/boss en LISTE d'éléments valides.

    Mono-élément aujourd'hui ("feu") ; forward-compatible multi-élément
    ("feu,glace" ou "feu glace"). "" / neutre → liste vide. Filtre les valeurs
    inconnues et déduplique en conservant l'ordre."""
    if not raw:
        return []
    parts = raw.replace(",", " ").split()
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        e = p.strip().lower()
        if e in _VALID_ELEMENTS and e not in seen:
            seen.add(e)
            out.append(e)
    return out
