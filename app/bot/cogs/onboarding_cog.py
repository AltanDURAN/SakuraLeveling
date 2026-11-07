"""Cog d'accueil des nouveaux joueurs — `/demarrer`.

Guide de démarrage clair (profil, combat, éléments/compétences, world boss).
À l'ARRIVÉE sur le serveur : carte de bienvenue illustrée (`welcome_card`) et
message court qui donne envie, avec des boutons vers le tutoriel et la
première zone (31/10/2026, demande de l'auteur).

NOTE : l'accueil AUTOMATIQUE à l'arrivée d'un membre (`on_member_join`)
nécessite l'intent privilégié **SERVER MEMBERS** (Discord Dev Portal +
`intents.members=True`). Tant qu'il n'est pas activé, on s'appuie sur la
commande `/demarrer`. Le listener ci-dessous est prêt mais dormant sans intent.
"""

from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.rank_roles import ensure_start_rank_role
from app.bot.rendering.welcome_card import compose_welcome_card
from app.infrastructure.encounters.farm_zone_loader import list_zones
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.domain.services import pacing_service
from app.infrastructure.pacing.pacing_loader import get_pacing

_logger = logging.getLogger(__name__)


def build_welcome_embed(display_name: str | None = None) -> discord.Embed:
    who = f" {display_name}" if display_name else ""
    raid = get_pacing().raid
    fight, close = pacing_service.fight_label(raid), pacing_service.close_label(raid)
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
            "**`/profil`** — ton perso, ton rang et tes stats.\n"
            "**`/stats`** — à chaque niveau tu gagnes **1 point de stats** : "
            "place-le en attaque, en défense ou en PV. C'est ta seule source de "
            "puissance brute.\n"
            "**`/daily`** — récompense quotidienne (reviens chaque jour !)."
        ),
        inline=False,
    )
    embed.add_field(
        name="2️⃣ Combats & progression",
        value=(
            "**`/tour`** — ton premier combat, tout de suite et à ta portée.\n"
            "Les **monstres** apparaissent ensuite dans les salons de zone : clique "
            "**Combattre**, puis **Lancer** quand le groupe est prêt, pour gagner XP, or "
            "et butin. Jusqu'au niveau 10, ton XP de combat est **doublée**.\n"
            "**`/arbre`** — chaque niveau donne aussi **1 point d'arbre** : "
            "bonus, passifs et, aux jonctions, des classes.\n"
            "**`/epreuve`** — réussis l'épreuve de ton rôle pour ouvrir une nouvelle zone."
        ),
        inline=False,
    )
    embed.add_field(
        name="3️⃣ Équipement 🛠️",
        value=(
            "Chaque monstre peut lâcher **la pièce qu'il porte**, dans une rareté "
            "tirée au sort (⚪ commun → 🔴 mythique). **`/forgeron`** **fusionne** "
            "deux copies identiques en une plus rare. Dès l'épique, une pièce "
            "révèle son **passif**.\n"
            "L'équipement donne des **%** de tes stats : il amplifie ce que tu as "
            "construit avec tes points.\n"
            "**`/alchimiste`** — potions de soin, de mana et élixirs, avec les "
            "matériaux des monstres."
        ),
        inline=False,
    )
    embed.add_field(
        name="4️⃣ Les éléments ✨",
        value=(
            "Chaque monstre a un élément. Ton attaque prend toute seule "
            "l'élément qui le frappe le plus fort, et ta **maîtrise** de cet "
            "élément décide du bonus (jusqu'à **+30 %**). Monte tes affinités en "
            "farmant des essences (`/affinites`, `/bestiaire monstres`)."
        ),
        inline=False,
    )
    embed.add_field(
        name="5️⃣ World Boss 👑",
        value=(
            f"Un boss apparaît chaque semaine. **Inscris-toi** (🤝) avant **{close}**, "
            f"le combat collectif se lance **automatiquement à {fight}**. Récompenses "
            "selon ta contribution, **butin exclusif** s'il tombe avant de repartir !"
        ),
        inline=False,
    )
    embed.set_footer(text="Nouveau ? /tuto : Hana te guide pas à pas (3 potions à la clé). /help pour tout le reste. 🌸")
    return embed


WELCOME_COLOR = discord.Color.from_rgb(255, 150, 195)
WELCOME_IMAGE = "bienvenue.png"


def build_join_embed(member_mention: str) -> discord.Embed:
    """Le message d'ARRIVÉE (la première chose qu'on voit sur le serveur) :
    court, RP, qui donne envie — le guide complet reste dans `/demarrer`."""
    tuto = f"<#{settings.tutorial_channel_id}>" if settings.tutorial_channel_id else "`/tuto`"
    rules = f"<#{settings.rules_channel_id}>" if settings.rules_channel_id else "`/reglement`"
    embed = discord.Embed(
        title="🌸 Les pétales annoncent un nouvel aventurier !",
        description=(
            f"{member_mention}, le vent du Grand Cerisier t'a porté jusqu'à nous.\n"
            "Des monstres sortent des terres sauvages, et la guilde cherche des héros. "
            "Ton nom est déjà inscrit au registre, au **Rang F**.\n\n"
            "⚔️ **Des combats en groupe**, filmés en vidéo, qu'on rejoint d'un clic\n"
            "🎒 **Un butin unique** sur chaque monstre, du commun au **mythique**\n"
            "🌳 **Trois voies** : frapper, protéger ou soigner\n"
            "✨ **Huit éléments** et des talents cachés que seule la voyante sait lire\n"
            "👑 **Un boss chaque semaine**, et le vrai ciel de Paris qui réveille les monstres\n\n"
            f"**Ton aventure commence ici :** accepte le règlement dans {rules}, puis Hana "
            f"t'attend dans {tuto} pour te guider. Au bout, **3 Potions du Grand Cerisier** 🧪 t'attendent."
        ),
        color=WELCOME_COLOR,
    )
    embed.set_image(url=f"attachment://{WELCOME_IMAGE}")
    embed.set_footer(text="Rang F débloqué · /help pour toutes les commandes · bonne chasse ! 🌸")
    return embed


def build_join_view(guild_id: int) -> discord.ui.View:
    """Boutons-liens (aucun état à garder : ils marchent aussi en MP et après
    un redémarrage)."""
    view = discord.ui.View(timeout=None)
    if settings.rules_channel_id:
        view.add_item(discord.ui.Button(
            label="Lire le règlement", emoji="📜", style=discord.ButtonStyle.link,
            url=f"https://discord.com/channels/{guild_id}/{settings.rules_channel_id}"))
    if settings.tutorial_channel_id:
        view.add_item(discord.ui.Button(
            label="Commencer le tutoriel", emoji="🌸", style=discord.ButtonStyle.link,
            url=f"https://discord.com/channels/{guild_id}/{settings.tutorial_channel_id}"))
    zone = next((z for z in list_zones() if z.get("channel_id")), None)
    if zone:
        view.add_item(discord.ui.Button(
            label=f"Foncer : {zone['name']}", emoji="⚔️", style=discord.ButtonStyle.link,
            url=f"https://discord.com/channels/{guild_id}/{zone['channel_id']}"))
    return view


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

        # 3. Carte de bienvenue (avatar, numéro d'aventurier) + message RP.
        try:
            card = await asyncio.to_thread(
                compose_welcome_card, member.display_name, member.display_avatar.url,
                member.guild.member_count)
        except Exception:
            _logger.warning("Onboarding: échec de la carte de bienvenue %s", member.id, exc_info=True)
            card = None

        def message() -> dict:
            embed = build_join_embed(member.mention)
            kwargs = {"embed": embed, "view": build_join_view(member.guild.id)}
            if card is not None:
                kwargs["file"] = discord.File(io.BytesIO(card), filename=WELCOME_IMAGE)
            else:
                embed.set_image(url=None)
                embed.set_thumbnail(url=member.display_avatar.url)
            return kwargs

        # 3a. MP de bienvenue (best-effort — peut être bloqué par le membre).
        try:
            await member.send(**message())
        except discord.DiscordException:
            pass

        # 3b. Message dans le salon d'accueil.
        channel_id = settings.welcome_channel_id
        if channel_id:
            channel = member.guild.get_channel(channel_id)
            if channel is not None:
                try:
                    await channel.send(content=member.mention, **message())
                except discord.DiscordException:
                    pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OnboardingCog(bot))
