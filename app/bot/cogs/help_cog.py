"""Cog `/help` — tutoriel paginé du bot.

`/help` (sans argument) ouvre un mini-tutoriel : une page d'intro (pitch du
bot + boucle de jeu + premiers pas) suivie d'une page par CATÉGORIE
thématique de commandes. Boutons précédent / suivant pour naviguer.

Pas de liste hardcodée des descriptions : on itère sur
`bot.tree.walk_commands()` pour récupérer la description LIVE de chaque
slash command, puis on range chaque commande dans sa catégorie via
`CATEGORIES`. Toute commande non mappée tombe dans « Autres » → rien n'est
jamais perdu si on en ajoute une plus tard.

Les commandes admin sont MASQUÉES par défaut. Elles restent accessibles via
`/help <command>` (ex : `/help admin set`) pour qui les cherche.

Avec paramètre `command` : embed détaillé pour une commande spécifique
(description + params + autocomplete sur le nom).
"""

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.views.help_view import HelpView


# Préfixes de groupes à ne PAS afficher dans le catalogue joueur.
HIDDEN_GROUP_PREFIXES = ("admin",)

# Catégories thématiques : (emoji, titre, sous-titre, {noms de commandes}).
# Le matching se fait sur le NOM DE TÊTE de la commande (ex : "boss spawn"
# → "boss"), donc un groupe entier se range d'un coup. L'ordre fixe l'ordre
# des pages. Une commande absente de tous les sets va dans « Autres ».
CATEGORIES: list[tuple[str, str, str, set[str]]] = [
    ("👤", "Profil & progression",
     "Ton personnage, sa classe, ses titres, son arbre et ta routine quotidienne.",
     {"profile", "gold", "class", "classes", "class_set", "skill",
      "title", "title_set", "cd", "daily", "daily_quest", "weekly_quest"}),
    ("⚔️", "Combat & aventure",
     "Affronte les monstres, les world bosses et les autres joueurs.",
     {"fight", "use", "boss", "bestiaire"}),
    ("🎒", "Équipement & inventaire",
     "Gère ton stuff, tes panoplies et tes loadouts perso.",
     {"inventory", "equipement", "equipement_list", "equip", "unequip",
      "equip_panoplie", "panoplie", "create_set", "equip_set", "delete_set"}),
    ("🛠️", "Artisanat & récolte",
     "Récolte des ressources puis fabrique / forge ton équipement.",
     {"gather", "craft", "craft_list", "forge", "forge_list",
      "craft_panoplie", "forge_panoplie"}),
    ("💰", "Économie & échanges",
     "Boutique, monnaie et commerce entre joueurs.",
     {"shop", "buy", "pay", "trade", "brocante"}),
    ("🏆", "Classements & utilitaires",
     "Compare-toi aux autres et trouve de l'aide.",
     {"top", "help", "ping", "chad"}),
]
_OTHERS = ("📂", "Autres", "Commandes diverses.", set())


def _build_intro_embed(total_cmds: int, n_pages: int) -> discord.Embed:
    """Page d'accueil du tutoriel : pitch + boucle de jeu + premiers pas."""
    embed = discord.Embed(
        title="🌸 Bienvenue dans SakuraLeveling",
        description=(
            "Un **RPG Discord** où tu fais grandir ton personnage : combats les "
            "monstres qui apparaissent dans le salon, récolte et forge ton "
            "équipement, débloque des compétences et grimpe dans les classements."
        ),
        color=discord.Color.magenta(),
    )
    embed.add_field(
        name="🎯 La boucle de jeu",
        value=(
            "**1.** ⚔️ **Combats** — des monstres spawnent tout seuls : rejoins le "
            "combat de groupe (ou défie un joueur avec `/fight`).\n"
            "**2.** 📈 **Progresse** — gagne XP, or et butin ; chaque niveau donne "
            "**1 point de compétence** à investir dans l'arbre (`/skill`).\n"
            "**3.** 🛠️ **Équipe-toi** — récolte (`/gather`), fabrique (`/craft`, "
            "`/forge`) et porte une panoplie complète (`/equip_panoplie`).\n"
            "**4.** 🧬 **Optimise** — choisis ta classe (`/class_set`), tes titres "
            "(`/title`) et ton build d'arbre.\n"
            "**5.** 🏆 **Brille** — quêtes (`/weekly`), classements (`/top`) et "
            "ladder de duels."
        ),
        inline=False,
    )
    embed.add_field(
        name="🚀 Premiers pas",
        value=(
            "• `/profile` — crée ton personnage et vois tout d'un coup d'œil.\n"
            "• `/daily` — ta récompense quotidienne (à faire chaque jour !).\n"
            "• `/gather` puis `/craft_list` — de quoi te fabriquer ton 1er stuff.\n"
            "• `/skill` — dépense tes points de compétence."
        ),
        inline=False,
    )
    embed.add_field(
        name="💡 Astuce",
        value=(
            "Tape `/help <commande>` pour le détail d'une commande précise "
            "(avec ses paramètres). Utilise ◀ ▶ pour parcourir les "
            f"**{n_pages - 1} catégories** ci-après."
        ),
        inline=False,
    )
    embed.set_footer(text=f"Page 1/{n_pages} · {total_cmds} commandes joueur")
    return embed


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
        # 1. Range chaque commande joueur dans sa catégorie thématique.
        buckets: dict[int, list[tuple[str, str]]] = {
            i: [] for i in range(len(CATEGORIES))
        }
        others: list[tuple[str, str]] = []
        total_cmds = 0
        for name, desc, _ in _walk_all_commands(self.bot, include_admin=False):
            total_cmds += 1
            top = name.split(" ", 1)[0]
            for i, (_emoji, _label, _sub, names) in enumerate(CATEGORIES):
                if top in names:
                    buckets[i].append((name, desc))
                    break
            else:
                others.append((name, desc))

        # 2. Construit la liste ordonnée des catégories non vides (+ Autres).
        sections: list[tuple[str, str, str, list[tuple[str, str]]]] = []
        for i, (emoji, label, sub, _names) in enumerate(CATEGORIES):
            if buckets[i]:
                sections.append((emoji, label, sub, sorted(buckets[i])))
        if others:
            sections.append((*_OTHERS[:3], sorted(others)))

        n_pages = len(sections) + 1  # +1 pour la page d'intro

        # 3. Page d'intro + une page par catégorie.
        pages: list[discord.Embed] = [_build_intro_embed(total_cmds, n_pages)]
        for idx, (emoji, label, sub, cmds) in enumerate(sections):
            embed = discord.Embed(
                title=f"{emoji} {label}",
                description=f"_{sub}_",
                color=discord.Color.blurple(),
            )
            # Découpe en plusieurs fields pour la limite de 1024 chars.
            current, field_idx = "", 1
            for cmd_name, cmd_desc in cmds:
                line = f"**`/{cmd_name}`** — {cmd_desc}\n"
                if len(current) + len(line) > 1000:
                    embed.add_field(
                        name="Commandes" if field_idx == 1 else "​",
                        value=current, inline=False,
                    )
                    current, field_idx = line, field_idx + 1
                else:
                    current += line
            if current:
                embed.add_field(
                    name="Commandes" if field_idx == 1 else "​",
                    value=current, inline=False,
                )
            embed.set_footer(
                text=(
                    f"Page {idx + 2}/{n_pages} · "
                    f"{len(cmds)} commande(s) · `/help <commande>` pour le détail"
                )
            )
            pages.append(embed)

        view = HelpView(author_id=interaction.user.id, pages=pages)
        await interaction.response.send_message(
            embed=pages[0], view=view, ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
