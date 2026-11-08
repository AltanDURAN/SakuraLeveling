"""Guides épinglés des salons du world boss et de la tour solo (07/11/2026,
demande de l'auteur) : le premier message du salon explique ce qu'on y fait.

Écrits à partir des règles du code (horaires du raid réglés dans Monde ›
Rythme, constantes de la tour et du raid) : le bot les réécrit quand un
réglage change, ils ne mentent jamais.
"""

from __future__ import annotations

from datetime import time

import discord

from app.domain.services import pacing_service
from app.domain.services.boss_assault import GUARDED_REDUCTION_PCT
from app.domain.services.boss_selection_service import MARGIN, TEAM_SIZE
from app.domain.services.tower_service import (
    BOSS_EVERY,
    BOSS_REWARD_MULT,
    DAILY_GOLD_PER_FLOOR,
    TOWER_FLOORS,
)
from app.domain.services.world_boss_scaling_service import WorldBossScalingService

#: Reconnaît un guide parmi les messages du bot (pied de page fixe).
GUIDE_FOOTER = "📌 Guide du salon · tenu à jour par le bot"
COLOR = discord.Color.from_rgb(255, 150, 195)

#: Bandeaux (titre, sous-titre, phrase, graine des pétales) et nom du fichier.
WORLD_BOSS_BANNER = ("WORLD BOSS", "Le raid de toute la semaine", "Tous ensemble, chaque soir, jusqu'à sa chute", 7311)
WORLD_BOSS_FILE = "world_boss.png"
TOWER_BANNER = ("TOUR SOLO", f"{TOWER_FLOORS} étages, un seul aventurier", "Ton record ne redescend jamais", 5150)
TOWER_FILE = "tour_solo.png"


def _pct(value: float) -> str:
    return f"{round(value * 100)} %"


def build_world_boss_guide(raid: pacing_service.RaidPacing, first_raid_level: int,
                           active_days: int) -> discord.Embed:
    """`first_raid_level` : niveau que doivent atteindre `TEAM_SIZE` joueurs
    actifs (un combat dans les `active_days` derniers jours) pour qu'un boss vienne."""
    fight, close = pacing_service.fight_label(raid), pacing_service.close_label(raid)
    arrival = f"{pacing_service.WEEKDAYS[raid.spawn_weekday]} à {pacing_service.time_label(time(raid.spawn_hour))}"
    last_day = pacing_service.WEEKDAYS[(raid.spawn_weekday - 1) % 7]
    scaling = WorldBossScalingService
    embed = discord.Embed(
        title="👑 Le world boss, le raid de la semaine",
        description=(
            f"Chaque **{arrival}**, un colosse s'installe dans ce salon pour **toute la semaine**. "
            "Tout le serveur l'affronte ensemble : chaque PV qu'on lui arrache est **définitif**, "
            "il ne se soigne jamais d'un jour à l'autre."
        ),
        color=COLOR,
    )
    embed.add_field(name="🤝 Participer", inline=False, value=(
        f"• Clique **Rejoindre** sous le boss, avant **{close}**.\n"
        f"• Chaque jour à **{fight}** (heure de Paris), tous les inscrits lancent l'assaut ensemble. "
        "La liste repart ensuite à zéro : on se réinscrit chaque jour.\n"
        "• **Un assaut par jour** et par joueur. Pas besoin d'être là : le combat se joue tout seul, "
        "sa vidéo puis son récapitulatif s'affichent ici."
    ))
    embed.add_field(name="💪 Plus on est nombreux…", inline=False, value=(
        f"Chaque combattant en plus donne **+{_pct(scaling.BONUS_PER_PARTICIPANT)} d'attaque, de défense "
        f"et de PV** à toute l'équipe (jusqu'à +{_pct(scaling.MAX_BONUS)}). Les élixirs d'Elna comptent."
    ))
    embed.add_field(name="⚔️ Ses mécaniques", inline=False, value=(
        "• **Phases** à 75, 50 et 25 % de ses PV : il change de tactique.\n"
        "• **Attaque ultime** : il la charge d'abord (c'est annoncé), puis frappe tout le groupe. "
        "Un allié qui le provoque l'encaisse seul.\n"
        f"• **Deux gardes** le protègent : tant qu'il en reste un, le boss prend {GUARDED_REDUCTION_PCT} % "
        "de dégâts en moins. L'équipe les abat d'abord ; ils reviennent à chaque assaut."
    ))
    embed.add_field(name="🎁 Récompenses", inline=False, value=(
        "• À sa chute, **chacun est payé selon sa contribution** : dégâts infligés, dégâts encaissés, soins. "
        "Le podium et le meilleur de chaque rôle gagnent bien plus, chacun tente sa chance sur le butin "
        "du boss, et le premier porte le titre **MVP des World Boss**.\n"
        f"• S'il tient encore debout après le dernier assaut (le **{last_day}**), **il repart** : chacun touche "
        "sa part selon les PV retirés, sans butin ni titre.\n"
        "• Les montants suivent ton niveau."
    ))
    embed.add_field(name="📅 Quel boss ?", inline=False, value=(
        "Il suit le niveau du serveur : il est choisi d'après le niveau médian des joueurs actifs "
        f"(un combat dans les {active_days} derniers jours). Pas de raid tant que {TEAM_SIZE} joueurs actifs "
        f"n'ont pas atteint le niveau **{first_raid_level}**."
    ))
    embed.add_field(name="📜 Commandes", inline=False, value=(
        "`/boss moi` ta contribution · `/boss historique` les semaines passées · `/bestiaire boss` les boss du jeu, à découvrir"
    ))
    embed.set_image(url=f"attachment://{WORLD_BOSS_FILE}")
    embed.set_footer(text=GUIDE_FOOTER)
    return embed


def first_raid_level(boss_levels: list[int]) -> int:
    """Le niveau à partir duquel le plus petit boss est à portée."""
    return max(1, min(boss_levels) - MARGIN) if boss_levels else 1


def build_tower_guide() -> discord.Embed:
    embed = discord.Embed(
        title=f"🗼 La tour solo, {TOWER_FLOORS} étages",
        description=(
            f"Une tour de **{TOWER_FLOORS} étages**, les mêmes pour tout le monde. L'étage N oppose des monstres "
            f"du niveau N, et un **boss** garde chaque dizaine (étages {BOSS_EVERY}, {2 * BOSS_EVERY}…). "
            "Ici, pas de groupe : tu montes **seul**, et ton record ne redescend jamais."
        ),
        color=COLOR,
    )
    embed.add_field(name="🎟️ Les tickets", inline=False, value=(
        "• **1 ticket par jour** (remis à minuit), **+1** avec la case Confort de l'arbre "
        "ou la bénédiction de Thalos.\n"
        "• Une **victoire garde ton ticket** : tu enchaînes les étages tant que tu gagnes.\n"
        "• Une **défaite le consomme**, sans te faire redescendre."
    ))
    embed.add_field(name="⚔️ Le combat", inline=False, value=(
        "Seul, PV et mana pleins, **sans potion ni élixir** : la tour mesure ton build, pas tes réserves. "
        "Tes vrais PV ne bougent pas.\n"
        "Il se joue en **vidéo**, comme en zone, puis son récapitulatif (récompenses, détails, journal) : "
        "après une victoire, l'étage suivant se tente de là.\n"
        "Un aventurier équilibré passe un étage de son niveau environ deux fois sur trois "
        "(une fois sur deux contre un boss). Un pur soutien peine seul : adapte ton build pour grimper."
    ))
    embed.add_field(name="🎁 Récompenses", inline=False, value=(
        "• **Premier passage** de chaque étage : de l'or et de l'XP à son niveau, "
        f"**×{BOSS_REWARD_MULT} sur un étage de boss**, qui donne aussi des matériaux de fusion de sa famille.\n"
        f"• **Récompense du jour** (bouton dans `/tour`) : **{DAILY_GOLD_PER_FLOOR} or par étage** de ton record, "
        "et des matériaux de fusion (1 de plus tous les 10 étages)."
    ))
    embed.add_field(name="📜 Commandes", inline=False, value=(
        "`/tour` ici : l'étage suivant, ses monstres, et les boutons pour le tenter ou prendre ta récompense "
        "du jour · `/classement tour` les records du serveur"
    ))
    embed.set_image(url=f"attachment://{TOWER_FILE}")
    embed.set_footer(text=GUIDE_FOOTER)
    return embed
