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

from app.infrastructure.config.settings import settings
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


def _compute_progress(title, kill_repo: PlayerKillRepository, player_id: int) -> int:
    """Renvoie la progression actuelle vers la condition du titre.
    Retourne 0 si le type n'est pas géré (extensibilité)."""
    if title.condition_type == "kills_family" and title.condition_target:
        return kill_repo.get_kills_for_family(player_id, title.condition_target)
    if title.condition_type == "kills_total":
        return kill_repo.get_total_kills(player_id)
    return 0


class TitleCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.channel_id != settings.beta_channel_id:
            message = (
                "🚧 Le bot est actuellement en phase de test.\n"
                "Utilisez le channel beta dédié."
            )
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return False
        return True

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
            kill_repo = PlayerKillRepository(session)
            unlocked_codes = title_repo.list_codes_for_player(profile.player.id)
            active_code = title_repo.get_active_title_code(profile.player.id)
            # Progression actuelle pour chaque titre verrouillé
            all_defs_local = list_definitions()
            progress_by_code: dict[str, int] = {}
            for d in all_defs_local:
                if d.code in unlocked_codes:
                    progress_by_code[d.code] = d.condition_value  # déjà au max
                else:
                    progress_by_code[d.code] = _compute_progress(
                        d, kill_repo, profile.player.id,
                    )

        all_defs = all_defs_local
        unlocked_defs = [d for d in all_defs if d.code in unlocked_codes]
        locked_defs = [d for d in all_defs if d.code not in unlocked_codes]

        ratio_unlocked = len(unlocked_defs)
        ratio_total = len(all_defs)
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
            lines = []
            for d in locked_defs:
                progress = progress_by_code.get(d.code, 0)
                # Description courte de la condition
                if d.condition_type == "kills_family" and d.condition_target:
                    cond_label = f"{d.condition_target} tués"
                elif d.condition_type == "kills_total":
                    cond_label = "monstres tués au total"
                elif d.condition_type == "duels_won":
                    cond_label = "duels gagnés"
                elif d.condition_type == "items_crafted":
                    cond_label = "items craftés"
                else:
                    cond_label = d.condition_type
                lines.append(
                    f"{d.icon} {d.name} — **{progress}/{d.condition_value}** "
                    f"{cond_label}"
                )
            embed.add_field(
                name="🔒 À débloquer", value="\n".join(lines)[:1024], inline=False
            )

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
