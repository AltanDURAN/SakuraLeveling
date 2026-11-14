"""Écran de `/admin acces` : l'aperçu des permissions qui vont changer, puis
un bouton pour les appliquer (parcours d'arrivée, 08/11/2026)."""

from __future__ import annotations

import discord

from app.bot.views._base import ExpiringView

from app.bot import access
from app.bot import access_plan as ap

COLOR = discord.Color.from_rgb(255, 150, 195)
#: Le parcours, en une ligne par étape.
JOURNEY = ("**Arrivée** — l'accueil et le règlement, en lecture seule\n"
           "**Règlement accepté → Rang F** — le tutoriel, la tour, la première zone\n"
           "**Tutoriel fini ou passé → Aventurier** — tout le reste (général, annonces, raid, records…)\n"
           "**Rangs gagnés à l'épreuve** — chaque zone pour son rang et les suivants")
_LIMIT = 3800


def summary(changes: list[ap.Change], limit: int = _LIMIT) -> str:
    """Une ligne par salon (qui le voyait → qui le verra), coupée à `limit`."""
    lines, size = [], 0
    for index, change in enumerate(changes):
        line = change.line
        if size + len(line) + 1 > limit:
            lines.append(f"… et {len(changes) - index} autre(s)")
            break
        lines.append(line)
        size += len(line) + 1
    return "\n".join(lines)


def build_access_embed(plan: ap.Plan) -> discord.Embed:
    if plan.changes:
        description = (f"**{len(plan.changes)} salon(s) à régler** — qui le voit : avant → après\n\n"
                       + summary(plan.changes))
    else:
        description = "✅ Tout est déjà en place : aucun salon à changer."
    embed = discord.Embed(title="🔐 Accès aux salons", description=description, color=COLOR)
    embed.add_field(name="Le parcours", value=JOURNEY, inline=False)
    if plan.private:
        embed.add_field(name="🔒 Laissés tels quels (salons d'équipe)",
                        value=", ".join(f"#{name}" for name in plan.private)[:1024], inline=False)
    embed.set_footer(text="Seuls @everyone, les rangs et Aventurier sont touchés, et seulement le droit de voir "
                          "(et d'écrire dans l'accueil et le règlement). Rien n'est retiré aux membres.")
    return embed


def build_result_embed(done: int, failed: list[str]) -> discord.Embed:
    embed = discord.Embed(title="🔐 Accès aux salons", color=COLOR if not failed else discord.Color.orange(),
                          description=f"✅ **{done} salon(s) réglé(s).**")
    if failed:
        embed.add_field(name=f"❌ {len(failed)} échec(s)", value="\n".join(failed)[:1024], inline=False)
    return embed


class AccessView(ExpiringView):
    def __init__(self, author_id: int, guild: discord.Guild) -> None:
        super().__init__(timeout=600)
        self.author_id = author_id
        self.guild = guild

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Cet aperçu ne t'est pas destiné.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Appliquer", emoji="🔐", style=discord.ButtonStyle.danger)
    async def apply_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="⏳ Réglage des salons…", view=None)
        # Plan relu (le serveur a pu changer) et recalculé après chaque passe.
        done, failed = await access.settle(self.guild, self.guild.fetch_channels)
        await interaction.edit_original_response(content=None, embed=build_result_embed(done, failed))

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Rien n'a été changé.", embed=None, view=None)
