"""Embeds de la tour solo (`/tour`) : l'état, un essai, une récompense."""

from __future__ import annotations

import discord

from app.application.use_cases.tower import TowerAttempt, TowerStatus
from app.bot.embeds.battle_summary_embeds import actions_label
from app.bot.embeds.encounter_combat_log_embeds import format_turn_action
from app.domain.services import tower_service as ts
from app.domain.services.mob_ability_service import MOB_ABILITY_SUMMARY
from app.domain.value_objects.battle_summary import BattleSummary
from app.domain.value_objects.player_reward import PlayerReward
from app.infrastructure.tower import tower_loader
from app.shared.enums import ELEMENT_EMOJIS, GOLD_EMOJI
from app.shared.formatters import format_int

#: Règle explicite, comme pour les épreuves (décision de l'auteur).
RULES = ("Seul, à PV et mana **pleins**, sans potion ni élixir. Tant que tu gagnes, "
         "tu gardes ton ticket et tu enchaînes ; une défaite coûte le ticket, jamais "
         "un étage — tu reprends où tu en étais.")


def _reward_text(reward: ts.TowerReward, material_names: dict[str, str] | None = None) -> str:
    parts = []
    if reward.gold:
        parts.append(f"{GOLD_EMOJI} {format_int(reward.gold)} or")
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


def floor_title(outcome: TowerAttempt) -> str:
    name = outcome.floor_data.get("name")
    return f"Étage {outcome.floor}" + (f" — {name}" if name else "")


def build_tower_summary(outcome: TowerAttempt, material_names: dict[str, str] | None = None) -> BattleSummary:
    """Le récapitulatif d'un essai, aux pages des combats de zone (08/11/2026) :
    récompenses (record et ticket en tête), détails (ce qu'il restait aux
    ennemis), journal."""
    result = outcome.result
    enemies = outcome.floor_data["enemies"]
    names = material_names or {}
    me = result.contributions[0] if result.contributions else None
    reward = PlayerReward(
        player_id=me.player_id if me else 0, user_id=me.user_id if me else 0,
        name=me.name if me else "?", avatar_url="",
        gold=outcome.reward.gold, xp=outcome.reward.xp, items=list(outcome.reward.materials),
        item_names={code: names.get(code, code) for code, _ in outcome.reward.materials},
        contribution=me, contribution_share=1.0 if outcome.victory else 0.0,
        level_before=outcome.new_level - 1 if outcome.new_level else 0, level_after=outcome.new_level,
        stat_points=outcome.stat_points, skill_points=outcome.skill_points,
    )
    plural = "s" if outcome.tickets_left > 1 else ""
    if outcome.victory:
        notes = [f"Victoire en **{actions_label(result.turns)}**. Nouveau record : **étage {outcome.best_floor}**.",
                 f"🎟️ Ticket gardé ({outcome.tickets_left} disponible{plural})."]
    else:
        left = sum(e["remaining_hp"] for e in result.enemies)
        notes = [f"Vaincu après **{actions_label(result.turns)}** ({format_int(left)} PV restaient aux ennemis).",
                 f"🎟️ Ticket perdu — {outcome.tickets_left} restant{plural}. "
                 "Ton record ne bouge pas : adapte ton build et reviens."]
    return BattleSummary(
        outcome="victory" if outcome.victory else "defeat", mob_name=floor_title(outcome),
        mob_image_name=enemies[0].get("image_name"), mob_family=enemies[0].get("family", ""),
        turns=result.turns, rewards=[reward], mob_count=len(enemies),
        journal=[format_turn_action(log) for log in result.turn_logs],
        kind="tour", notes=notes, enemies=list(result.enemies),
    )


def build_daily_embed(reward: ts.TowerReward, best_floor: int,
                      material_names: dict[str, str] | None = None) -> discord.Embed:
    return discord.Embed(
        title="🎁 Récompense de la tour",
        description=f"Étage record **{best_floor}** : {_reward_text(reward, material_names)}",
        color=discord.Color.gold(),
    )
