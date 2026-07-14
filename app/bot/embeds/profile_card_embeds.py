"""Embeds des sous-cartes du /profil (navigation par boutons, façon fiche web).

La carte principale reste la bannière PNG. Les sous-cartes (inventaire,
équipement, compétences, titres, affinités, carrière, duel) sont des embeds
affichés à la volée quand le joueur clique un bouton, avec retour arrière.
"""

from __future__ import annotations

import discord

from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS, ELEMENT_LABELS
from app.shared.formatters import format_int


def _color(rank_label: str) -> discord.Color:
    from app.bot.rendering.profile_banner import _rank_color
    r, g, b = _rank_color(rank_label or "")
    return discord.Color.from_rgb(r, g, b)


def build_main_image_embed(display_name: str, rank_label: str, attachment_filename: str) -> discord.Embed:
    """Embed conteneur de la bannière (carte principale)."""
    e = discord.Embed(title=f"🌸 {display_name}", color=_color(rank_label))
    e.set_image(url=f"attachment://{attachment_filename}")
    e.set_footer(text="Clique un bouton pour voir le détail · retour avec ⬅️")
    return e


def _sub(d: dict, title: str) -> discord.Embed:
    e = discord.Embed(title=title, color=_color(d.get("rank", "")))
    e.set_author(name=d["display_name"], icon_url=d.get("avatar_url") or None)
    return e


def build_inventory_embed(d: dict) -> discord.Embed:
    e = _sub(d, "🎒 Inventaire")
    inv = d.get("inventory") or []
    if inv:
        lines = [f"• **{it['name']}** ×{it['quantity']}" for it in inv]
        e.description = "\n".join(lines[:45])
        if len(inv) > 45:
            e.set_footer(text=f"… et {len(inv) - 45} autre(s)")
    else:
        e.description = "_Inventaire vide._"
    return e


def build_equipment_embed(d: dict) -> discord.Embed:
    e = _sub(d, "🛡️ Équipement")
    eq = d.get("equipment") or []
    if eq:
        e.description = "\n".join(f"**{it['slot']}** — {it['name']}" for it in eq)
    else:
        e.description = "_Aucun équipement porté._"
    return e


def build_skills_embed(d: dict) -> discord.Embed:
    e = _sub(d, "🔮 Compétences élémentaires")
    lines = []
    for s in d.get("skills") or []:
        if s["code"]:
            lines.append(f"**Slot {s['slot']}** — {s['label']}")
        else:
            lines.append(f"**Slot {s['slot']}** — _vide_")
    e.description = "\n".join(lines) or "_Aucune compétence équipée._"
    e.set_footer(text="Équipe tes compétences avec /competences")
    return e


def build_titles_embed(d: dict) -> discord.Embed:
    e = _sub(d, "🏷️ Titres")
    titles = d.get("titles") or []
    if titles:
        e.description = "\n".join(
            (f"★ **{t['name']}**" if t["active"] else f"• {t['name']}") for t in titles
        )
    else:
        e.description = "_Aucun titre débloqué._"
    return e


def build_affinities_embed(d: dict) -> discord.Embed:
    e = _sub(d, "✨ Affinités & essences")
    aff = d.get("affinities") or {}
    ess = d.get("essences") or {}
    lines = []
    for el in ALL_ELEMENTS:
        code = el.value
        lines.append(
            f"{ELEMENT_EMOJIS.get(code, '')} **{ELEMENT_LABELS.get(code, code)}** — "
            f"{int(aff.get(code, 0))}/100 · {int(ess.get(code, 0))} ess."
        )
    e.description = "\n".join(lines)
    e.set_footer(text="Farme des monstres pour gagner des essences et monter tes affinités")
    return e


def build_career_embed(d: dict) -> discord.Embed:
    e = _sub(d, "📈 Carrière")
    c = d.get("career") or {}
    fields = [
        ("💀 Tués", c.get("total_kills", 0)),
        ("⚔️ Combats", c.get("combats_fought", 0)),
        ("🏆 V / D", f"{c.get('combats_won', 0)} / {c.get('combats_lost', 0)}"),
        ("💰 Or amassé", c.get("gold_earned_total", 0)),
        ("💢 Dégâts infligés", c.get("damage_dealt_total", 0)),
        ("🛡️ Dégâts encaissés", c.get("damage_tanked_total", 0)),
        ("💚 PV soignés", c.get("hp_healed_total", 0)),
        ("🌀 Esquives", c.get("dodges_total", 0)),
    ]
    for name, val in fields:
        e.add_field(name=name, value=f"**{format_int(int(val)) if str(val).lstrip('-').isdigit() else val}**", inline=True)
    return e


def build_duel_embed(d: dict) -> discord.Embed:
    e = _sub(d, "⚔️ Duel 1v1")
    duel = d.get("duel")
    if duel:
        e.add_field(name="Rang ladder", value=f"**#{duel['rank_position']}**", inline=True)
        e.add_field(name="Victoires", value=f"**{duel['wins']}**", inline=True)
        e.add_field(name="Défaites", value=f"**{duel['losses']}**", inline=True)
    else:
        e.description = "_Tu n'as pas encore combattu en duel. Défie un joueur avec /duel._"
    return e


def build_all_subcards(d: dict) -> dict:
    """Construit tous les embeds de sous-carte pour un profil."""
    return {
        "inventory": build_inventory_embed(d),
        "equipment": build_equipment_embed(d),
        "skills": build_skills_embed(d),
        "titles": build_titles_embed(d),
        "affinities": build_affinities_embed(d),
        "career": build_career_embed(d),
        "duel": build_duel_embed(d),
    }
