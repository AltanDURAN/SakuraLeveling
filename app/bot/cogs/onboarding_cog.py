"""Cog d'accueil des nouveaux joueurs — `/demarrer`.

Guide de démarrage clair (profil, combat, éléments/compétences, world boss).

NOTE : l'accueil AUTOMATIQUE à l'arrivée d'un membre (`on_member_join`)
nécessite l'intent privilégié **SERVER MEMBERS** (Discord Dev Portal +
`intents.members=True`). Tant qu'il n'est pas activé, on s'appuie sur la
commande `/demarrer`. Le listener ci-dessous est prêt mais dormant sans intent.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.infrastructure.config.settings import settings


def build_welcome_embed(display_name: str | None = None) -> discord.Embed:
    who = f" {display_name}" if display_name else ""
    embed = discord.Embed(
        title="🌸 Bienvenue dans Sakura Leveling !",
        description=(
            f"Salut{who} ! Voici comment démarrer ton aventure."
        ),
        color=discord.Color.magenta(),
    )
    embed.add_field(
        name="1️⃣ Ton personnage",
        value=(
            "**`/profil`** — crée ton perso et vois tes stats + tes **affinités "
            "élémentaires** (tirées à ta création).\n"
            "**`/daily`** — récompense quotidienne (reviens chaque jour !)."
        ),
        inline=False,
    )
    embed.add_field(
        name="2️⃣ Combats & progression",
        value=(
            "Les **monstres** apparaissent dans les salons de zone : clique "
            "**Rejoindre** pour combattre en groupe et gagner XP/or/loot.\n"
            "**`/arbre`** — dépense tes points de compétence (moteur de stats).\n"
            "**`/equip`**, **`/boutique`**, **`/craft_list`** — équipe-toi."
        ),
        inline=False,
    )
    embed.add_field(
        name="3️⃣ Éléments & compétences ✨",
        value=(
            "**`/competences`** — équipe **2 compétences élémentaires** "
            "(offensive/défense/support). L'offensive fixe ton **élément "
            "d'attaque** → **±30%** de dégâts selon l'élément de l'ennemi.\n"
            "**`/bestiaire`** — vois l'élément et les **faiblesses** des monstres.\n"
            "_L'art de l'adaptation : choisis ton build selon l'ennemi !_"
        ),
        inline=False,
    )
    embed.add_field(
        name="4️⃣ World Boss 👑",
        value=(
            "Un boss apparaît chaque semaine. **Inscris-toi** (🤝) avant **20h50**, "
            "le combat collectif se lance **automatiquement à 21h**. Récompenses "
            "proportionnelles à ta contribution + **loot exclusif** !"
        ),
        inline=False,
    )
    embed.set_footer(text="Tape /help pour la liste complète des commandes. Bon jeu ! 🌸")
    return embed


class OnboardingCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="demarrer",
        description="Guide de démarrage pour les nouveaux joueurs",
    )
    async def demarrer(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=build_welcome_embed(interaction.user.display_name), ephemeral=True
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        # Dormant sans l'intent SERVER MEMBERS. Poste un accueil dans le salon
        # de bienvenue si configuré.
        channel_id = getattr(settings, "welcome_channel_id", 0)
        if not channel_id:
            return
        channel = member.guild.get_channel(channel_id)
        if channel is None:
            return
        try:
            await channel.send(content=member.mention, embed=build_welcome_embed(member.display_name))
        except discord.DiscordException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OnboardingCog(bot))
