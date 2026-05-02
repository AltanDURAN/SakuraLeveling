"""Cog `/help` — liste dynamique des commandes du bot.

Pas de hardcoded list : on itère sur `bot.tree.walk_commands()` pour
récupérer toutes les slash commands enregistrées et leurs descriptions.
Cela inclut automatiquement les nouvelles commandes ajoutées dans le
futur, sans avoir à toucher ce fichier.

Sans paramètre : embed listant toutes les commandes par cog.
Avec paramètre `command` : embed détaillé pour une commande spécifique
(description + params + autocomplete sur le nom).
"""

import discord
from discord import app_commands
from discord.ext import commands


def _walk_all_commands(bot: commands.Bot):
    """Yield (full_name, description, command_obj) pour toutes les slash
    commands, y compris celles dans des `app_commands.Group` (ex : /admin).
    """
    for cmd in bot.tree.walk_commands():
        if isinstance(cmd, app_commands.Group):
            continue  # le groupe lui-même n'est pas appelable
        yield cmd.qualified_name, (cmd.description or ""), cmd


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="help",
        description="Liste les commandes du bot ou détaille une commande spécifique",
    )
    @app_commands.describe(command="Nom d'une commande (autocomplete) — laisse vide pour la liste complète")
    async def help_command(
        self,
        interaction: discord.Interaction,
        command: str | None = None,
    ) -> None:
        if command:
            await self._send_detail(interaction, command)
        else:
            await self._send_list(interaction)

    @help_command.autocomplete("command")
    async def command_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower()
        out: list[app_commands.Choice[str]] = []
        for name, desc, _ in _walk_all_commands(self.bot):
            if current_lower in name.lower() or current_lower in desc.lower():
                # name limité à 100 chars (Discord), value à 100 aussi
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
        for full_name, desc, cmd in _walk_all_commands(self.bot):
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

    async def _send_list(self, interaction: discord.Interaction) -> None:
        # Regroupe par préfixe (le 1er token avant le 1er espace = nom du groupe
        # ou la commande elle-même). /admin set_class → group "admin", /pay → "pay".
        groups: dict[str, list[tuple[str, str]]] = {}
        for name, desc, _ in _walk_all_commands(self.bot):
            top = name.split(" ", 1)[0]
            groups.setdefault(top, []).append((name, desc))

        embed = discord.Embed(
            title="📖 Catalogue des commandes",
            description=(
                "Tape `/help <command>` pour le détail d'une commande "
                "(autocomplete disponible)."
            ),
            color=discord.Color.blurple(),
        )

        # Ordonner les groupes (les commandes simples d'abord, puis admin & co)
        ordered = sorted(groups.keys(), key=lambda g: (g in ("admin",), g))
        for group_name in ordered:
            cmds = sorted(groups[group_name], key=lambda x: x[0])
            lines = [f"`/{name}` — {desc}" for name, desc in cmds]
            # Discord cap: 1024 chars per field value
            value = "\n".join(lines)
            if len(value) > 1000:
                value = value[:1000] + "\n_…_"
            label = (
                f"📂 /{group_name} ({len(cmds)})"
                if len(cmds) > 1 or " " in cmds[0][0]
                else f"📂 /{group_name}"
            )
            embed.add_field(name=label, value=value, inline=False)

        embed.set_footer(text=f"{sum(len(v) for v in groups.values())} commandes au total")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
