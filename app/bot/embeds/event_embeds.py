"""Messages des événements non-combat (coffre, petite fille, forge sacrée).

Sortis du cog le 11/11/2026 : le bot les poste, et la page Événements du site
admin montre les MÊMES messages en aperçu, avec les réglages en cours
d'édition (rien n'est écrit en double).
"""

from __future__ import annotations

import discord

#: Boutons sous chaque message d'apparition (emoji, libellé, style Discord) — miroir
#: des vues persistantes d'`event_cog` (vérifié par les tests).
BUTTONS: dict[str, list[tuple[str, str, str]]] = {
    "chest": [("🗝️", "Ouvrir le coffre", "success")],
    "little_girl": [("🤝", "Aider la petite fille", "success"), ("🚶", "Ignorer", "secondary")],
    "sacred_forge": [("🔨", "Forger un équipement", "primary")],
}


# ------------------------------------------------------------------ coffre --
def chest_spawn_embed() -> discord.Embed:
    return discord.Embed(
        title="🎁 Un coffre au trésor apparaît !",
        description=(
            "Un coffre mystérieux se matérialise… **Le premier qui l'ouvre "
            "rafle le butin !** Serez-vous le plus rapide ?"
        ),
        color=discord.Color.gold(),
    )


def chest_opened_embed(winner: str, reward_text: str) -> discord.Embed:
    return discord.Embed(
        title="🎁 Coffre ouvert !",
        description=f"{winner} a été le plus rapide et remporte **{reward_text}** !",
        color=discord.Color.dark_gold(),
    )


def chest_expired_embed() -> discord.Embed:
    return discord.Embed(
        title="💨 Le coffre s'est volatilisé…",
        description="Personne ne l'a ouvert à temps. Un autre apparaîtra bientôt — ouvre l'œil !",
        color=discord.Color.dark_grey(),
    )


# ------------------------------------------------------------ petite fille --
def girl_spawn_embed(minutes: int) -> discord.Embed:
    return discord.Embed(
        title="👧 Une petite fille apparaît…",
        description=(
            "Une petite fille en pleurs surgit au détour du chemin et implore "
            "de l'aide. Mais dans ces terres maudites, tout n'est pas ce qu'il "
            "paraît… **Aider** ou **ignorer** ?\n\n"
            f"⏳ Le sort de chacun sera scellé dans **{minutes} minutes**. "
            "Tout le monde peut participer."
        ),
        color=discord.Color.purple(),
    )


def girl_outcome_tag(consequence) -> str:
    """Le sort d'un participant, en une ligne (`LittleGirlConsequence`)."""
    from app.shared.formatters import format_int

    if consequence.grant_title:
        return "🛡️ **titre Ma survie avant tout !**"
    if consequence.buff_multiplier > 0:
        return f"😇 buff +{round((consequence.buff_multiplier - 1) * 100)}% ({consequence.buff_hours}h)"
    if consequence.debuff_multiplier > 0:
        return f"💔 debuff ÷{round(1 / consequence.debuff_multiplier) if consequence.debuff_multiplier else 2} ({consequence.debuff_hours}h)"
    if consequence.gold_loss > 0 or consequence.halve_hp:
        return f"😈 −{format_int(consequence.gold_loss)} or & moitié PV"
    return "🚶 rien"


def girl_result_embed(is_trap: bool, lines: list[str]) -> discord.Embed:
    if is_trap:
        embed = discord.Embed(
            title="😈 C'était un piège !",
            description=(
                "La « petite fille » était un **monstre déguisé** venu piéger "
                "les âmes charitables. Ceux qui l'ont aidée l'ont payé cher ; "
                "ceux qui l'ont ignorée ont eu le nez creux."
            ),
            color=discord.Color.dark_red(),
        )
    else:
        embed = discord.Embed(
            title="😇 C'était une vraie petite fille.",
            description=(
                "Une enfant réellement perdue. Ceux qui l'ont aidée sont "
                "bénis ; ceux qui l'ont ignorée le regrettent amèrement."
            ),
            color=discord.Color.green(),
        )
    embed.add_field(name="Sort des participants",
                    value="\n".join(lines[:20]) if lines else "Personne n'a participé…", inline=False)
    return embed


# ------------------------------------------------------------ forge sacrée --
def forge_spawn_embed(minutes: int, max_level: int) -> discord.Embed:
    return discord.Embed(
        title="🔨 La forge sacrée s'embrase !",
        description=(
            "Une forge légendaire apparaît, brûlant d'une flamme divine. "
            "Pendant **{m} minutes**, chacun peut y **renforcer un seul de ses "
            "pièces** (une seule fois). Chaque niveau ajoute +1 % aux stats de "
            "la pièce — jusqu'au **niveau {lv}**.\n\nClique **Forger** "
            "et choisis ta pièce !"
        ).format(m=minutes, lv=max_level),
        color=discord.Color.orange(),
    )


def forge_closed_embed(forged_count: int) -> discord.Embed:
    return discord.Embed(
        title="🔥 La forge sacrée s'est éteinte.",
        description=(
            f"La flamme divine s'éteint. **{forged_count}** aventurier(s) "
            "ont renforcé un équipement."
        ),
        color=discord.Color.dark_orange(),
    )
