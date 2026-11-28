"""Le groupe de commandes `/admin` et ses choix communs, partagés par
`AdminCog` et ses mixins (`admin_shop`, `admin_items`) : toutes les
sous-commandes doivent s'accrocher au MÊME objet groupe (28/11/2026, audit)."""

import discord
from discord import app_commands

from app.domain.services.gear_service import RARITY_LABELS, RARITY_ORDER

# Masquée pour les joueurs dans le menu de Discord (`@admin_only` reste
# la vraie protection).
admin = app_commands.Group(
    name="admin",
    description="Commandes administrateur",
    default_permissions=discord.Permissions(administrator=True),
)

_RARITY_CHOICES = [
    app_commands.Choice(name=RARITY_LABELS[r], value=r.value) for r in RARITY_ORDER
]

#: Ressources de `/admin set|give|remove` (une commande par action : la limite
#: de Discord est de 25 sous-commandes par groupe).
_RESOURCE_CHOICES = [
    app_commands.Choice(name="Or", value="gold"),
    app_commands.Choice(name="XP", value="xp"),
    app_commands.Choice(name="Points d'arbre", value="skill_points"),
    app_commands.Choice(name="Points de stats", value="stat_points"),
    app_commands.Choice(name="PV courants", value="current_hp"),
    app_commands.Choice(name="Mana courant", value="current_mana"),
    app_commands.Choice(name="Daily streak", value="daily_streak"),
    app_commands.Choice(name="Étage record de la tour", value="tower_floor"),
]
