"""Le menu du site admin — SOURCE UNIQUE (11/11/2026).

Le menu du haut (base.html), le fil d'Ariane de chaque page et les cartes de
l'accueil (dashboard.html) le lisent tous : une page ajoutée ici apparaît
partout, au même endroit, avec le même nom. Avant, l'accueil avait sa propre
liste (Rythme, Offrande et Images en lot y manquaient, Fêtes n'était pas dans
le même groupe).

Chaque entrée : (lien, nom, icône, phrase de l'accueil, clé du compteur).
La clé renvoie à un compteur calculé par `dashboard_router` (None = aucun).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    href: str
    label: str
    icon: str
    desc: str
    count: str | None = None


@dataclass(frozen=True)
class NavGroup:
    label: str
    items: tuple[NavItem, ...]


NAV: tuple[NavGroup, ...] = (
    NavGroup("📊 Surveillance", (
        NavItem("/admin/monitoring", "Vue d'ensemble", "🧭", "Activité, économie, combats, progression : l'état du jeu en un coup d'œil."),
        NavItem("/admin/monitoring/activity", "Activité", "⏱️", "Qui joue, quand, combien de temps, et qui revient."),
        NavItem("/admin/monitoring/economy", "Économie", "💰", "D'où vient l'or, où il part, qui le détient."),
        NavItem("/admin/monitoring/combat", "Combats", "⚔️", "Monstres farmés, résistants, groupes, lune."),
        NavItem("/admin/monitoring/meta", "Méta", "🧩", "Pièces portées, raretés, builds qui marchent."),
        NavItem("/admin/monitoring/progression", "Progression", "📈", "Le rythme réel contre le design, et les joueurs bloqués."),
        NavItem("/admin/monitoring/players", "Joueurs suivis", "👥", "Chaque joueur comparé aux autres : temps de jeu, rythme, investissement."),
        NavItem("/admin/monitoring/alerts", "Alertes", "🚨", "Comportements suspects, équilibrage, économie, rétention — avec leurs seuils."),
        NavItem("/admin/monitoring/report", "Rapport", "📰", "La semaine contre la précédente, faits marquants."),
    )),
    NavGroup("👥 Joueurs", (
        NavItem("/admin/players", "Joueurs", "👥", "Fiches : voir, éditer, inventaire, équipement, reset.", "players"),
        NavItem("/admin/roles", "Rôles", "🏷️", "Rôles du serveur Discord et leurs membres."),
        NavItem("/admin/actions", "Actions", "⚡", "Donner de l'or, de l'XP, des objets ; faire apparaître un monstre, un boss, un événement."),
    )),
    NavGroup("🗺️ Monde", (
        NavItem("/admin/mobs", "Monstres", "👾", "Stats, élément, famille, pièce portée, image.", "mobs"),
        NavItem("/admin/zones", "Zones", "🗺️", "Salons, familles, décors par élément, essences.", "zones"),
        NavItem("/admin/pacing", "Rythme", "⏱️", "Délai entre deux monstres, meutes, horaires du raid, lune."),
        NavItem("/admin/scenes", "Scènes", "🎬", "Placement des monstres sur leurs décors, formations des meutes."),
        NavItem("/admin/familles", "Familles", "🧬", "Familles de monstres et le matériau commun qu'elles lâchent.", "families"),
        NavItem("/admin/world-bosses", "World Bosses", "🐉", "Le boss de la semaine : images, arène, stats.", "bosses"),
        NavItem("/admin/events", "Événements", "🎲", "Coffre, petite fille, forge sacrée : aperçus, réglages, historique.", "events"),
        NavItem("/admin/seasonal", "Fêtes", "🎉", "Avent, Noël, sucres d'orge, boutiques d'événement, Nouvel An."),
    )),
    NavGroup("📦 Objets", (
        NavItem("/admin/items", "Objets", "🎒", "Équipement, ressources, consommables, outils, cosmétiques.", "items"),
        NavItem("/admin/items/images", "Images en lot", "🖼️", "Déposer toutes les images d'objets d'un coup."),
        NavItem("/admin/shop", "Boutique", "🏪", "Ce que Sorn vend, à quel prix.", "shop"),
        NavItem("/admin/offering", "Offrande", "🙏", "La jauge d'or du serveur et ses divinités."),
        NavItem("/admin/cards", "Cartes", "🎴", "Cartes à collectionner : réglages des boosters, cartes, images."),
    )),
    NavGroup("📈 Progression", (
        NavItem("/admin/skill-tree/builder", "Arbre de compétences", "🌳", "Builder visuel : cases, effets, formes, liens.", "skill_nodes"),
        NavItem("/admin/titles", "Titres", "🏷️", "Titres à débloquer, conditions et effets.", "titles"),
        NavItem("/admin/quests", "Quêtes", "📜", "Modèles des quêtes quotidiennes et hebdomadaires.", "quests"),
    )),
)


def locate(path: str) -> tuple[NavGroup | None, NavItem | None]:
    """Le groupe et l'entrée du menu d'une page : le lien le plus long qui
    préfixe son chemin (/admin/items/images n'allume pas /admin/items)."""
    best: tuple[NavGroup | None, NavItem | None] = (None, None)
    for group in NAV:
        for item in group.items:
            if path.startswith(item.href) and (best[1] is None or len(item.href) > len(best[1].href)):
                best = (group, item)
    return best
