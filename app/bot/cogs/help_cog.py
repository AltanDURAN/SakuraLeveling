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
        # Regroupe par préfixe pour ranger visuellement, mais Discord limite
        # à 25 fields par embed → si on dépasse, on consolide les commandes
        # simples (sans groupe `/xxx yyy`) dans un seul field "Joueur".
        groups: dict[str, list[tuple[str, str]]] = {}
        for name, desc, _ in _walk_all_commands(self.bot):
            top = name.split(" ", 1)[0] if " " in name else "_player_"
            groups.setdefault(top, []).append((name, desc))

        embed = discord.Embed(
            title="📖 Catalogue des commandes",
            description=(
                "Tape `/help <command>` pour le détail d'une commande "
                "(autocomplete disponible)."
            ),
            color=discord.Color.blurple(),
        )

        # _player_ d'abord, puis admin & autres groupes triés
        ordered = sorted(
            groups.keys(),
            key=lambda g: (g != "_player_", g in ("admin",), g),
        )
        max_fields = 24  # garde 1 slot pour le footer "+ N autres"
        added = 0
        for group_name in ordered:
            if added >= max_fields:
                break
            cmds = sorted(groups[group_name], key=lambda x: x[0])
            lines = [f"`/{name}` — {desc}" for name, desc in cmds]
            value = "\n".join(lines)
            if len(value) > 1000:
                value = value[:1000] + "\n_…_"
            label = (
                "📂 Joueur"
                if group_name == "_player_"
                else f"📂 /{group_name} ({len(cmds)})"
            )
            embed.add_field(name=label, value=value, inline=False)
            added += 1

        total = sum(len(v) for v in groups.values())
        if added < len(groups):
            remaining = len(groups) - added
            embed.add_field(
                name="…",
                value=f"_+{remaining} groupe(s) supplémentaires masqués_",
                inline=False,
            )

        embed.set_footer(text=f"{total} commandes au total")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
