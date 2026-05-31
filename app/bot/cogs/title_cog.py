"""Cog des titres : /title @target et /title_set <code>.

- /title [target]      : affiche tous les titres débloqués (incluant l'actif)
- /title_set [title]   : choisit le titre à afficher dans /profile (cosmétique).
                         Sans argument, désactive l'affichage du titre actuel.

Les effets passifs des titres (bonus dégâts vs famille, réduction dégâts
subis) sont actifs DÈS QUE le titre est débloqué — l'équipement via
/title_set n'a qu'un rôle d'affichage.
"""

import discord
from discord import app_commands
from discord.ext import commands

from app.application.services.exclusive_title_service import ExclusiveTitleService
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.player_career_stats_repository import (
    PlayerCareerStatsRepository,
)
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_title_repository import (
    PlayerTitleRepository,
)
from app.infrastructure.db.session import get_db_session
from app.infrastructure.titles.title_loader import (
    get_definition,
    list_definitions,
)

from app.bot.cogs._mixins import BetaChannelOnlyMixin


def _build_progress_label(
    title,
    *,
    profile,
    session,
) -> str:
    """Renvoie la ligne de progression formatée à afficher pour un titre
    NON encore débloqué. Gère tous les `condition_type` connus, y compris
    les exclusifs (qui n'ont pas de seuil numérique mais un détenteur
    actuel).
    """
    kill_repo = PlayerKillRepository(session)
    career_repo = PlayerCareerStatsRepository(session)
    excl = ExclusiveTitleService(session)
    pid = profile.player.id

    if title.condition_type == "kills_family" and title.condition_target:
        progress = kill_repo.get_kills_for_family(pid, title.condition_target)
        return f"**{progress}/{title.condition_value}** {title.condition_target} tués"

    if title.condition_type == "kills_total":
        progress = kill_repo.get_total_kills(pid)
        return f"**{progress}/{title.condition_value}** monstres tués au total"

    if title.condition_type == "kills_mob" and title.condition_target:
        progress = kill_repo.get_kills_per_mob(pid).get(title.condition_target, 0)
        return f"**{progress}/{title.condition_value}** kills sur ce mob"

    if title.condition_type == "dodges_total":
        career = career_repo.get_or_create(pid)
        return (
            f"**{getattr(career, 'dodges_total', 0)}/{title.condition_value}** "
            "esquives en combat de groupe"
        )

    if title.condition_type == "daily_streak":
        return (
            f"**{profile.resources.daily_streak}/{title.condition_value}** "
            "jours de daily streak"
        )

    if title.condition_type == "duel_top1":
        # Titre exclusif : montrer le détenteur actuel (rang 1 du ladder)
        # plutôt qu'un compteur 0/0 qui n'a aucun sens.
        holder_id = excl.current_holder("champion_1v1")
        if holder_id is None:
            return "_Personne ne le détient encore. Atteignez la 1re place du ladder duel._"
        if holder_id == pid:
            return "_Vous êtes le détenteur actuel !_"
        holder_profile = PlayerRepository(session).get_profile_by_player_id(holder_id)
        holder_name = (
            holder_profile.player.display_name if holder_profile else f"#{holder_id}"
        )
        return f"Détenteur actuel : **{holder_name}** (top 1 du ladder duel)"

    if title.condition_type == "kills_record":
        # Titre exclusif Farmer Fou : afficher record actuel + détenteur
        # + écart pour le viewer.
        holder_id = excl.current_holder("farmer_fou")
        viewer_total = kill_repo.get_total_kills(pid)
        if holder_id is None:
            return (
                f"_Personne ne détient encore le record._ "
                f"Vous : **{viewer_total}** kills."
            )
        holder_total = kill_repo.get_total_kills(holder_id)
        if holder_id == pid:
            return (
                f"_Vous êtes le détenteur actuel avec_ **{holder_total}** kills."
            )
        holder_profile = PlayerRepository(session).get_profile_by_player_id(holder_id)
        holder_name = (
            holder_profile.player.display_name if holder_profile else f"#{holder_id}"
        )
        # On dépasse strictement, donc il faut au moins +1 par rapport au détenteur
        gap = max(0, holder_total - viewer_total + 1)
        return (
            f"Détenteur : **{holder_name}** avec **{holder_total}** kills · "
            f"vous : **{viewer_total}** (il vous manque **{gap}**)"
        )

    return f"_Condition : {title.condition_type}_"


class TitleCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="title", description="Afficher les titres débloqués d'un joueur"
    )
    @app_commands.describe(target="Joueur ciblé (par défaut : vous)")
    async def title(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        target_member = target or interaction.user
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(target_member.id)
            if profile is None:
                await interaction.response.send_message(
                    f"❌ {target_member.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return
            title_repo = PlayerTitleRepository(session)
            unlocked_codes = title_repo.list_codes_for_player(profile.player.id)
            active_code = title_repo.get_active_title_code(profile.player.id)

            all_defs_local = list_definitions()
            unlocked_defs = [d for d in all_defs_local if d.code in unlocked_codes]
            locked_defs = [d for d in all_defs_local if d.code not in unlocked_codes]

            # Progression formatée pour chaque titre encore verrouillé.
            # On reste DANS le `with session` pour pouvoir requêter kill_repo /
            # career_repo / duel_repo / exclusive_service au besoin.
            progress_label_by_code: dict[str, str] = {
                d.code: _build_progress_label(d, profile=profile, session=session)
                for d in locked_defs
            }

        ratio_unlocked = len(unlocked_defs)
        ratio_total = len(all_defs_local)
        embed = discord.Embed(
            title=f"🏷️ Titres de {target_member.display_name}",
            description=f"**{ratio_unlocked}** débloqué(s) sur **{ratio_total}** au total.",
            color=discord.Color.gold(),
        )

        if unlocked_defs:
            lines = []
            for d in unlocked_defs:
                marker = " ⭐" if d.code == active_code else ""
                lines.append(f"{d.icon} **{d.name}** (`{d.code}`){marker}\n  _{d.description}_")
            embed.add_field(name="✅ Débloqués", value="\n".join(lines)[:1024], inline=False)

        if locked_defs:
            # On groupe en plusieurs fields pour ne pas dépasser la limite
            # de 1024 caractères par field (le tableau peut faire 13+ titres
            # avec les 9 Chasseur Légendaire, 4 nouveaux et les 2 exclusifs).
            lines = []
            for d in locked_defs:
                lines.append(
                    f"{d.icon} **{d.name}** — {progress_label_by_code.get(d.code, '?')}"
                )

            # Découpe en chunks <= 1000 chars (laisse de la marge)
            chunks: list[list[str]] = [[]]
            current_len = 0
            for line in lines:
                if current_len + len(line) + 1 > 1000 and chunks[-1]:
                    chunks.append([])
                    current_len = 0
                chunks[-1].append(line)
                current_len += len(line) + 1

            for idx, chunk in enumerate(chunks):
                name = "🔒 À débloquer" if idx == 0 else f"🔒 À débloquer (suite {idx + 1})"
                embed.add_field(name=name, value="\n".join(chunk), inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="title_set",
        description="Choisir le titre affiché dans votre profil",
    )
    @app_commands.describe(
        title="Code du titre à afficher (laisser vide pour désactiver)"
    )
    async def title_set(
        self,
        interaction: discord.Interaction,
        title: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            title_repo = PlayerTitleRepository(session)

            if title is None:
                title_repo.set_active(profile.player.id, None)
                await interaction.followup.send(
                    "✅ Aucun titre actif. Votre profil n'affiche plus de titre.",
                    ephemeral=True,
                )
                return

            title_def = get_definition(title)
            if title_def is None:
                await interaction.followup.send(
                    f"❌ Titre `{title}` introuvable.", ephemeral=True
                )
                return

            success = title_repo.set_active(profile.player.id, title)
            if not success:
                await interaction.followup.send(
                    f"❌ Vous n'avez pas débloqué **{title_def.name}**.",
                    ephemeral=True,
                )
                return

        await interaction.followup.send(
            f"✅ Titre actif : {title_def.icon} **{title_def.name}**.", ephemeral=True
        )

    @title_set.autocomplete("title")
    async def title_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                return []
            unlocked = PlayerTitleRepository(session).list_codes_for_player(
                profile.player.id
            )
        defs = [d for d in list_definitions() if d.code in unlocked]
        current_lower = current.lower()
        return [
            app_commands.Choice(name=f"{d.icon} {d.name} ({d.code})", value=d.code)
            for d in defs
            if current_lower in d.code.lower() or current_lower in d.name.lower()
        ][:25]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TitleCog(bot))
