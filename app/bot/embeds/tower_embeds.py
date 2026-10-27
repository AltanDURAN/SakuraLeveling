"""Embeds de la tour solo (`/tour`) : l'état, un essai, une récompense."""

from __future__ import annotations

import discord

from app.application.use_cases.tower import TowerAttempt, TowerStatus
from app.domain.services import tower_service as ts
from app.domain.services.mob_ability_service import MOB_ABILITY_SUMMARY
from app.infrastructure.tower import tower_loader
from app.shared.enums import ELEMENT_EMOJIS
from app.shared.formatters import format_int

#: Règle explicite, comme pour les épreuves (décision de l'auteur).
RULES = ("Seul, à PV et mana **pleins**, sans potion ni élixir. Tant que tu gagnes, "
         "tu gardes ton ticket et tu enchaînes ; une défaite coûte le ticket, jamais "
         "un étage — tu reprends où tu en étais.")


def _reward_text(reward: ts.TowerReward, material_names: dict[str, str] | None = None) -> str:
    parts = []
    if reward.gold:
        parts.append(f"💰 {format_int(reward.gold)} or")
    if reward.xp:
        parts.append(f"✨ {format_int(reward.xp)} XP")
    for code, qty in reward.materials:
        parts.append(f"🧩 {qty} × {(material_names or {}).get(code, code)}")
    return " · ".join(parts) or "—"


def floor_lines(floor_data: dict) -> str:
    """Les ennemis de l'étage, dans l'ordre de la formation, avec leur capacité."""
    lines = []
    for e in floor_data.get("enemies", []):
        emoji = ELEMENT_EMOJIS.get(e.get("element", ""), "")
        crown = "👑 " if e.get("boss") else ""
        line = f"{crown}**{e['name']}** {emoji} — {format_int(e['max_hp'])} PV · {format_int(e['attack'])} ATK"
        ability = MOB_ABILITY_SUMMARY.get(e["code"])
        if ability:
            line += f"\n  ↳ _{ability}_"
        lines.append(line)
    return "\n".join(lines) or "—"


def build_status_embed(state: TowerStatus, name: str, material_names: dict[str, str] | None = None
                       ) -> discord.Embed:
    embed = discord.Embed(
        title="🗼 La Tour",
        description=(f"**{name}** — record : étage **{state.best_floor}** / {ts.TOWER_FLOORS}\n"
                     f"🎟️ Tickets : **{state.tickets.available}** / {state.tickets.allowance} aujourd'hui"
                     + ("" if state.tickets.has_bonus else " _(+1 avec la case « Confort » de l'arbre)_")),
        color=discord.Color.dark_purple(),
    )
    if state.next_floor is None or state.floor is None:
        embed.add_field(name="🏆 Sommet atteint", value="Tu as franchi les 100 étages.", inline=False)
    else:
        floor = state.floor
        title = f"Étage {state.next_floor} · niveau {floor['level']}"
        if floor.get("name"):
            title += f" — {floor['name']}"
        if floor.get("boss"):
            title = "👑 " + title
        embed.add_field(name=title, value=floor_lines(floor), inline=False)
        embed.add_field(
            name="Premier passage",
            value=_reward_text(ts.first_clear_reward(state.next_floor, tower_loader.floor_material(state.next_floor)),
                               material_names),
            inline=False,
        )
    daily = _reward_text(state.daily, material_names) if not state.daily.is_empty else \
        "Franchis un premier étage pour la débloquer."
    embed.add_field(
        name="🎁 Récompense du jour" + (" (prise ✅)" if state.daily_claimed else ""),
        value=f"{daily}\n_Elle grandit avec ton étage record, pas avec ton niveau._",
        inline=False,
    )
    embed.set_footer(text=RULES)
    return embed


def build_attempt_embed(outcome: TowerAttempt, material_names: dict[str, str] | None = None,
                        log_lines: int = 8) -> discord.Embed:
    result = outcome.result
    floor = outcome.floor_data
    title = f"Étage {outcome.floor}" + (f" — {floor['name']}" if floor.get("name") else "")
    if outcome.victory:
        embed = discord.Embed(title=f"🗼 {title} : franchi !", color=discord.Color.green())
        desc = f"Victoire en {result.turns} actions. Nouveau record : **étage {outcome.best_floor}**."
        if not outcome.reward.is_empty:
            desc += f"\n**Premier passage** : {_reward_text(outcome.reward, material_names)}"
        desc += f"\n🎟️ Ticket gardé ({outcome.tickets_left} disponible{'s' if outcome.tickets_left > 1 else ''})."
    else:
        embed = discord.Embed(title=f"🗼 {title} : défaite", color=discord.Color.red())
        left = sum(e["remaining_hp"] for e in result.enemies)
        desc = (f"Vaincu après {result.turns} actions ({format_int(left)} PV restaient aux ennemis).\n"
                f"🎟️ Ticket perdu — {outcome.tickets_left} restant{'s' if outcome.tickets_left > 1 else ''}. "
                "Ton record ne bouge pas : adapte ton build et reviens.")
    embed.description = desc
    lines = []
    for log in result.turn_logs[-log_lines:]:
        text = " ".join(a for a in log.player_actions if a) or log.mob_action
        if text:
            lines.append(f"• {text[:180]}")
    if lines:
        embed.add_field(name="Fin du combat", value="\n".join(lines)[:1024], inline=False)
    return embed


def build_daily_embed(reward: ts.TowerReward, best_floor: int,
                      material_names: dict[str, str] | None = None) -> discord.Embed:
    return discord.Embed(
        title="🎁 Récompense de la tour",
        description=f"Étage record **{best_floor}** : {_reward_text(reward, material_names)}",
        color=discord.Color.gold(),
    )
