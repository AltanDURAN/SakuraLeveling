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

import logging

from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.rank_roles import ensure_start_rank_role
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session

_logger = logging.getLogger(__name__)


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
            "**`/equiper`**, **`/boutique`**, **`/recettes`** — équipe-toi."
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
        # Début d'aventure : on crée le profil (idempotent) et on attribue le
        # rôle Rang F pour débloquer l'accès à la première zone de farm.
        try:
            with get_db_session() as session:
                PlayerRepository(session).get_or_create_by_discord_id(
                    discord_id=interaction.user.id,
                    username=interaction.user.name,
                    display_name=interaction.user.display_name,
                )
        except Exception:
            _logger.warning("demarrer: échec création profil %s", interaction.user.id, exc_info=True)
        if isinstance(interaction.user, discord.Member):
            await ensure_start_rank_role(interaction.user)
        await interaction.response.send_message(
            embed=build_welcome_embed(interaction.user.display_name), ephemeral=True
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Accueil complet d'un nouveau membre :
        1. l'enregistre dans la base des joueurs (crée son profil + affinités
           + compétences de départ),
        2. lui attribue le rôle par défaut (Sakura Leveling),
        3. lui souhaite la bienvenue + lui donne les bases (embed guide) en DM
           et/ou dans le salon d'accueil.
        Chaque étape est best-effort : un échec ne bloque pas les autres."""
        if member.bot:
            return
        # Restreint l'accueil au serveur du jeu (le bot peut être dans d'autres
        # serveurs qu'on ne veut pas peupler dans la base des joueurs).
        if settings.discord_guild_id and member.guild.id != settings.discord_guild_id:
            return

        # 1. Enregistrement en base (idempotent).
        try:
            with get_db_session() as session:
                PlayerRepository(session).get_or_create_by_discord_id(
                    discord_id=member.id,
                    username=member.name,
                    display_name=member.display_name,
                )
        except Exception:
            _logger.warning("Onboarding: échec création profil %s", member.id, exc_info=True)

        # 2. Attribution du rôle par défaut.
        role_id = settings.default_member_role_id
        if role_id:
            role = member.guild.get_role(role_id)
            if role is not None:
                try:
                    await member.add_roles(role, reason="Nouveau membre — rôle auto")
                except discord.DiscordException as exc:
                    _logger.warning("Onboarding: échec rôle %s → %s : %s", role_id, member.id, exc)

        # 2b. Rang F (accès à la première zone de farm) — best-effort.
        await ensure_start_rank_role(member)

        embed = build_welcome_embed(member.display_name)

        # 3a. DM de bienvenue (best-effort — peut être bloqué par le membre).
        try:
            await member.send(embed=embed)
        except discord.DiscordException:
            pass

        # 3b. Message dans le salon d'accueil.
        channel_id = settings.welcome_channel_id
        if channel_id:
            channel = member.guild.get_channel(channel_id)
            if channel is not None:
                try:
                    await channel.send(content=member.mention, embed=embed)
                except discord.DiscordException:
                    pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OnboardingCog(bot))
