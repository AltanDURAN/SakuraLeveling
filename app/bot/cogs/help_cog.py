"""Cog `/help` — liste paginée des commandes joueur.

Pas de hardcoded list : on itère sur `bot.tree.walk_commands()` pour
récupérer toutes les slash commands enregistrées et leurs descriptions.
Le catalogue affiche **une catégorie par page** avec boutons précédent /
suivant pour naviguer.

Les commandes admin sont MASQUÉES par défaut (pas pertinentes pour les
joueurs). Elles restent accessibles via `/help admin set` pour qui les
cherche directement.

Avec paramètre `command` : embed détaillé pour une commande spécifique
(description + params + autocomplete sur le nom).
"""

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.views.help_view import HelpView


# Préfixes de groupes à ne PAS afficher dans le catalogue joueur.
HIDDEN_GROUP_PREFIXES = ("admin",)

# Libellés et emojis par catégorie. Les groupes inconnus prennent un
# emoji par défaut.
GROUP_LABELS: dict[str, tuple[str, str]] = {
    "_player_":   ("Joueur — commandes principales", "🎮"),
    "boss":       ("World boss", "👑"),
    "brocante":   ("Brocante (marketplace P2P)", "🛍️"),
    "trade":      ("Échanges entre joueurs", "💱"),
}


def _walk_all_commands(bot: commands.Bot, include_admin: bool = False):
    """Yield (full_name, description, command_obj) pour toutes les slash
    commands. Filtre les groupes admin par défaut."""
    for cmd in bot.tree.walk_commands():
        if isinstance(cmd, app_commands.Group):
            continue
        full_name = cmd.qualified_name
        if not include_admin:
            top = full_name.split(" ", 1)[0]
            if top in HIDDEN_GROUP_PREFIXES:
                continue
        yield full_name, (cmd.description or ""), cmd


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="help",
        description="Liste les commandes du bot ou détaille une commande spécifique",
    )
    @app_commands.describe(
        command="Nom d'une commande (autocomplete) — laisse vide pour le catalogue paginé",
    )
    async def help_command(
        self,
        interaction: discord.Interaction,
        command: str | None = None,
    ) -> None:
        if command:
            await self._send_detail(interaction, command)
        else:
            await self._send_paginated_list(interaction)

    @help_command.autocomplete("command")
    async def command_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        # Pour /help <command>, on autorise aussi les commandes admin (un
        # admin peut vouloir voir le détail d'/admin set par exemple).
        current_lower = current.lower()
        out: list[app_commands.Choice[str]] = []
        for name, desc, _ in _walk_all_commands(self.bot, include_admin=True):
            if current_lower in name.lower() or current_lower in desc.lower():
                out.append(
                    app_commands.Choice(
                        name=f"/{name} — {desc}"[:100],
                        value=name[:100],
                    )
                )
            if len(out) >= 25:
                break
        return out

    async def _send_detail(self, interaction: discord.Interaction, name: str) -> None:
        for full_name, desc, cmd in _walk_all_commands(self.bot, include_admin=True):
            if full_name == name:
                embed = discord.Embed(
                    title=f"📖 /{full_name}",
                    description=desc or "_Pas de description._",
                    color=discord.Color.blurple(),
                )
                params = getattr(cmd, "parameters", []) or []
                if params:
                    param_lines = []
                    for p in params:
                        required = "" if p.required else " _(optionnel)_"
                        p_desc = p.description or "—"
                        param_lines.append(f"• **`{p.name}`**{required} : {p_desc}")
                    embed.add_field(
                        name="Paramètres",
                        value="\n".join(param_lines),
                        inline=False,
                    )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        await interaction.response.send_message(
            f"❌ Commande `{name}` introuvable.", ephemeral=True
        )

    async def _send_paginated_list(self, interaction: discord.Interaction) -> None:
        # Regroupe par préfixe : `/pay` → "_player_", `/boss spawn` → "boss"
        groups: dict[str, list[tuple[str, str]]] = {}
        for name, desc, _ in _walk_all_commands(self.bot, include_admin=False):
            top = name.split(" ", 1)[0] if " " in name else "_player_"
            groups.setdefault(top, []).append((name, desc))

        # Page joueur d'abord, puis groupes alphabétique
        ordered = sorted(
            groups.keys(),
            key=lambda g: (g != "_player_", g),
        )

        total_cmds = sum(len(v) for v in groups.values())
        pages: list[discord.Embed] = []

        for idx, group_name in enumerate(ordered):
            label, emoji = GROUP_LABELS.get(
                group_name, (f"/{group_name}", "📂"),
            )
            cmds = sorted(groups[group_name], key=lambda x: x[0])
            embed = discord.Embed(
                title=f"{emoji} {label}",
                description=(
                    f"_{len(cmds)} commande(s) dans cette page._\n"
                    f"Tape `/help <commande>` pour le détail (autocomplete dispo)."
                ),
                color=discord.Color.blurple(),
            )

            # Découpe en chunks pour respecter la limite de 1024 chars/field
            current_value = ""
            field_idx = 1
            for cmd_name, cmd_desc in cmds:
                line = f"`/{cmd_name}` — {cmd_desc}\n"
                if len(current_value) + len(line) > 1000:
                    embed.add_field(
                        name=(
                            "Commandes" if field_idx == 1
                            else f"Commandes (suite {field_idx})"
                        ),
                        value=current_value,
                        inline=False,
                    )
                    current_value = line
                    field_idx += 1
                else:
                    current_value += line
            if current_value:
                embed.add_field(
                    name=(
                        "Commandes" if field_idx == 1
                        else f"Commandes (suite {field_idx})"
                    ),
                    value=current_value,
                    inline=False,
                )

            embed.set_footer(
                text=(
                    f"Page {idx + 1}/{len(ordered)} · "
                    f"{total_cmds} commandes joueur au total"
                )
            )
            pages.append(embed)

        if not pages:
            await interaction.response.send_message(
                "ℹ️ Aucune commande disponible.", ephemeral=True,
            )
            return

        view = HelpView(author_id=interaction.user.id, pages=pages)
        await interaction.response.send_message(
            embed=pages[0], view=view, ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
